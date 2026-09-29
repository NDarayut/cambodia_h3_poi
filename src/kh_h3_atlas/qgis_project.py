"""Build a styled QGIS project for the atlas. Runs under the SYSTEM Python with PyQGIS.

Usage: /usr/bin/python3 qgis_project.py OUT.qgz FEATURES.gpkg LAYER [POI.gpkg ...]
Not imported by the pipeline package (PyQGIS is not in the uv environment).
"""

import sys
from pathlib import Path

from qgis.core import (
    QgsApplication,
    QgsClassificationQuantile,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFillSymbol,
    QgsGraduatedSymbolRenderer,
    QgsMarkerSymbol,
    QgsProject,
    QgsRasterLayer,
    QgsReferencedRectangle,
    QgsRendererRange,
    QgsSingleSymbolRenderer,
    QgsStyle,
    QgsVectorLayer,
)

NO_OUTLINE = {"outline_style": "no"}


def hex_layer(uri: str, name: str, subset: str | None = None) -> QgsVectorLayer:
    lyr = QgsVectorLayer(uri, name, "ogr")
    if not lyr.isValid():
        raise SystemExit(f"invalid layer: {uri}")
    if subset:
        lyr.setSubsetString(subset)
    return lyr


def quantile(lyr: QgsVectorLayer, field: str, ramp: str, classes: int = 7) -> None:
    r = QgsGraduatedSymbolRenderer(field)
    r.setClassificationMethod(QgsClassificationQuantile())
    r.setSourceSymbol(QgsFillSymbol.createSimple(NO_OUTLINE))
    r.setSourceColorRamp(QgsStyle.defaultStyle().colorRamp(ramp))
    r.updateClasses(lyr, classes)
    lyr.setRenderer(r)


def manual(
    lyr: QgsVectorLayer, field: str, bounds: list[tuple[float, float, str]], ramp: str
) -> None:
    color_ramp = QgsStyle.defaultStyle().colorRamp(ramp)
    ranges = []
    for i, (lo, hi, label) in enumerate(bounds):
        sym = QgsFillSymbol.createSimple(NO_OUTLINE)
        sym.setColor(color_ramp.color(0.15 + 0.85 * i / max(len(bounds) - 1, 1)))
        ranges.append(QgsRendererRange(lo, hi, sym, label))
    lyr.setRenderer(QgsGraduatedSymbolRenderer(field, ranges))


def single(lyr: QgsVectorLayer, color: str, opacity: float = 0.8) -> None:
    sym = QgsFillSymbol.createSimple({**NO_OUTLINE, "color": color})
    lyr.setRenderer(QgsSingleSymbolRenderer(sym))
    lyr.setOpacity(opacity)


def main() -> None:
    out, gpkg, layer, *poi_gpkgs = sys.argv[1:]
    app = QgsApplication([], False)
    app.initQgis()
    proj = QgsProject.instance()
    proj.setTitle("Cambodia H3 POI Atlas")
    proj.setCrs(QgsCoordinateReferenceSystem("EPSG:3857"))
    root = proj.layerTreeRoot()
    uri = f"{gpkg}|layername={layer}"

    # --- basemap (bottom) ---
    osm = QgsRasterLayer(
        "type=xyz&url=https://tile.openstreetmap.org/{z}/{x}/{y}.png&zmax=19&zmin=0",
        "OpenStreetMap",
        "wms",
    )
    proj.addMapLayer(osm, False)

    # --- hexagon views of the same feature table ---
    pop = hex_layer(uri, "Population per hexagon", '"population" > 0')
    quantile(pop, "population", "YlOrRd")
    pop.setOpacity(0.8)

    npoi = hex_layer(uri, "POIs per hexagon (all groups)", '"n_poi" > 0')
    manual(
        npoi,
        "n_poi",
        [
            (1, 1, "1"),
            (2, 4, "2–4"),
            (5, 9, "5–9"),
            (10, 24, "10–24"),
            (25, 99, "25–99"),
            (100, 100000, "100+"),
        ],
        "Blues",
    )
    npoi.setOpacity(0.85)

    gaps = []
    for grp, color in [("health", "#d03b3b"), ("education", "#eb6834"), ("finance", "#4a3aa7")]:
        g = hex_layer(
            uri,
            f"No {grp} POI within ~2.5 km (1,000+ people)",
            f'"population" >= 1000 AND "n_{grp}_k2" = 0',
        )
        single(g, color)
        gaps.append(g)

    data_gap = hex_layer(uri, "Data gap: 200+ people, no POIs at all", '"data_gap"')
    single(data_gap, "#7a7973", 0.7)

    full = hex_layer(uri, "All hexagons (query this layer)")
    full.setRenderer(
        QgsSingleSymbolRenderer(
            QgsFillSymbol.createSimple(
                {"color": "0,0,0,0", "outline_color": "#52514e", "outline_width": "0.1"}
            )
        )
    )
    full.setScaleBasedVisibility(True)
    full.setMinimumScale(100000)  # only draw outlines when zoomed in past 1:100,000

    # --- POI points ---
    points = []
    for p in poi_gpkgs:
        name = Path(p).stem
        pl = QgsVectorLayer(f"{p}|layername={name}", f"POIs ({name.removeprefix('poi_')})", "ogr")
        if pl.isValid():
            pl.setRenderer(
                QgsSingleSymbolRenderer(
                    QgsMarkerSymbol.createSimple(
                        {
                            "name": "circle",
                            "color": "#2a78d6",
                            "size": "1.6",
                            "outline_color": "white",
                            "outline_width": "0.2",
                        }
                    )
                )
            )
            pl.setScaleBasedVisibility(True)
            pl.setMinimumScale(250000)
            points.append(pl)

    # --- layer tree: top of list draws on top ---
    for pl in points:
        proj.addMapLayer(pl, False)
        root.addLayer(pl)
    proj.addMapLayer(full, False)
    root.addLayer(full)
    grp_gaps = root.addGroup("Service gaps (k2 = hexagon + 2 rings)")
    for g in gaps:
        proj.addMapLayer(g, False)
        grp_gaps.addLayer(g)
    proj.addMapLayer(data_gap, False)
    root.addLayer(data_gap)
    proj.addMapLayer(npoi, False)
    root.addLayer(npoi)
    proj.addMapLayer(pop, False)
    root.addLayer(pop)
    root.addLayer(osm)

    # Default visibility: basemap + population + points; the rest one click away
    for lyr in [npoi, data_gap, *gaps]:
        root.findLayer(lyr.id()).setItemVisibilityChecked(False)
    grp_gaps.setItemVisibilityChecked(False)

    extent = QgsCoordinateTransform(pop.crs(), proj.crs(), proj).transformBoundingBox(full.extent())
    proj.viewSettings().setDefaultViewExtent(QgsReferencedRectangle(extent, proj.crs()))

    proj.writeEntryBool("Paths", "/Absolute", False)  # relative paths: repo stays portable
    if not proj.write(out):
        raise SystemExit(f"could not write {out}")
    print(f"QGIS project written: {out} ({len(proj.mapLayers())} layers)")
    app.exitQgis()


if __name__ == "__main__":
    main()
