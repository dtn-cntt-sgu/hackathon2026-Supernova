-- Imported OSM way geometries are kept intact. osm2pgsql supplies osm_id.
local roads = osm2pgsql.define_way_table('osm_import_roads', {
    { column = 'osm_node_ids', type = 'jsonb' },
    { column = 'street_name', type = 'text' },
    { column = 'highway', type = 'text' },
    { column = 'access', type = 'text' },
    { column = 'oneway', type = 'text' },
    { column = 'bridge', type = 'text' },
    { column = 'tunnel', type = 'text' },
    { column = 'geom', type = 'linestring', projection = 4326 },
})

function osm2pgsql.process_way(object)
    if not object.tags.highway or object.tags.area == 'yes' then
        return
    end
    roads:insert({
        osm_node_ids = object.nodes,
        street_name = object.tags.name,
        highway = object.tags.highway,
        access = object.tags.access,
        oneway = object.tags.oneway,
        bridge = object.tags.bridge,
        tunnel = object.tags.tunnel,
        geom = object:as_linestring(),
    })
end
