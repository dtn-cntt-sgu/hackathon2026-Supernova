"""Frozen baseline schema: never import live application models into old revisions."""
import sqlalchemy as sa
import geoalchemy2

metadata = sa.MetaData()

sa.Table('hcmc_district_boundaries', metadata,
sa.Column('district_id', sa.String(length=64), nullable=False),
sa.Column('name', sa.String(length=128), nullable=False),
sa.Column('name_en', sa.String(length=128), nullable=True),
sa.Column('shape_name_raw', sa.String(length=128), nullable=True),
sa.Column('province', sa.String(length=128), nullable=False),
sa.Column('source', sa.String(length=255), nullable=False),
sa.Column('source_dataset_id', sa.String(length=64), nullable=False),
sa.Column('boundary_year', sa.Integer(), nullable=False),
sa.Column('license', sa.String(length=64), nullable=False),
sa.Column('geom', geoalchemy2.types.Geometry(geometry_type='MULTIPOLYGON', srid=4326, dimension=2, from_text='ST_GeomFromEWKT', name='geometry', nullable=False), nullable=False),
sa.PrimaryKeyConstraint('district_id')
)
sa.Table('hydrology_bulletins', metadata,
sa.Column('content_sha256', sa.String(length=64), nullable=False),
sa.Column('source_url', sa.Text(), nullable=False),
sa.Column('bulletin_number', sa.String(length=64), nullable=False),
sa.Column('bulletin_date', sa.String(length=10), nullable=False),
sa.Column('issued_at', sa.DateTime(timezone=True), nullable=False),
sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=False),
sa.Column('source_unit', sa.String(length=16), nullable=False),
sa.Column('vertical_datum', sa.String(length=64), nullable=False),
sa.Column('source_name', sa.String(length=255), nullable=False),
sa.PrimaryKeyConstraint('content_sha256')
)
sa.Table('hydrology_observations', metadata,
sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
sa.Column('station_id', sa.String(length=64), nullable=False),
sa.Column('station_name', sa.String(length=255), nullable=False),
sa.Column('river_name', sa.String(length=128), nullable=False),
sa.Column('district', sa.String(length=128), nullable=True),
sa.Column('latitude', sa.Float(), nullable=False),
sa.Column('longitude', sa.Float(), nullable=False),
sa.Column('water_level_m', sa.Float(), nullable=False),
sa.Column('alarm_level', sa.Integer(), nullable=False),
sa.Column('vertical_datum', sa.String(length=64), nullable=False),
sa.Column('measurement_type', sa.String(length=32), nullable=False),
sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
sa.Column('quality_status', sa.String(length=32), nullable=False),
sa.Column('source_name', sa.String(length=255), nullable=False),
sa.Column('source_url', sa.String(length=512), nullable=True),
sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
sa.PrimaryKeyConstraint('id')
)
sa.Table('road_segments', metadata,
sa.Column('osm_way_id', sa.BigInteger(), autoincrement=False, nullable=False),
sa.Column('street_name', sa.String(length=255), nullable=True),
sa.Column('is_flood_prone_history', sa.Boolean(), nullable=True),
sa.Column('geom', geoalchemy2.types.Geometry(geometry_type='LINESTRING', srid=4326, dimension=2, from_text='ST_GeomFromEWKT', name='geometry', nullable=False), nullable=False),
sa.Column('highway', sa.String(), nullable=True),
sa.Column('access', sa.String(), nullable=True),
sa.Column('oneway', sa.String(), nullable=True),
sa.Column('bridge', sa.String(), nullable=True),
sa.Column('tunnel', sa.String(), nullable=True),
sa.Column('length_meters', sa.Float(), nullable=True),
sa.Column('osm_extract_at', sa.DateTime(timezone=True), nullable=True),
sa.Column('source_url', sa.String(), nullable=True),
sa.Column('source_license', sa.String(), nullable=True),
sa.Column('source_pbf_md5', sa.String(), nullable=True),
sa.Column('imported_at', sa.DateTime(timezone=True), nullable=True),
sa.PrimaryKeyConstraint('osm_way_id')
)
sa.Table('traffic_news_articles', metadata,
sa.Column('id', sa.String(length=64), nullable=False),
sa.Column('canonical_url', sa.String(length=1024), nullable=False),
sa.Column('source_name', sa.String(length=128), nullable=False),
sa.Column('title', sa.String(length=512), nullable=False),
sa.Column('summary', sa.Text(), nullable=False),
sa.Column('category', sa.String(length=64), nullable=False),
sa.Column('severity', sa.String(length=32), nullable=False),
sa.Column('event_status', sa.String(length=32), nullable=False),
sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=False),
sa.Column('event_at', sa.DateTime(timezone=True), nullable=True),
sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
sa.Column('latitude', sa.Float(), nullable=True),
sa.Column('longitude', sa.Float(), nullable=True),
sa.Column('location_confidence', sa.String(length=32), nullable=False),
sa.Column('geocoding_status', sa.String(length=32), nullable=False),
sa.Column('verification_status', sa.String(length=32), nullable=False),
sa.Column('image_url', sa.String(length=1024), nullable=True),
sa.Column('geom', geoalchemy2.types.Geometry(geometry_type='POINT', srid=4326, dimension=2, from_text='ST_GeomFromEWKT', name='geometry'), nullable=True),
sa.PrimaryKeyConstraint('id')
)
sa.Table('users', metadata,
sa.Column('id', sa.String(length=64), nullable=False),
sa.Column('provider', sa.String(length=32), nullable=False),
sa.Column('provider_account_id', sa.String(length=255), nullable=False),
sa.Column('email', sa.String(length=255), nullable=False),
sa.Column('display_name', sa.String(length=255), nullable=False),
sa.Column('avatar_url', sa.String(length=512), nullable=True),
sa.Column('is_active', sa.Boolean(), nullable=False),
sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
sa.PrimaryKeyConstraint('id')
)
sa.Table('historical_flood_points', metadata,
sa.Column('id', sa.String(length=64), nullable=False),
sa.Column('street_name', sa.String(length=255), nullable=False),
sa.Column('district', sa.String(length=100), nullable=True),
sa.Column('cause', sa.String(length=50), nullable=False),
sa.Column('reported_years', sa.String(length=50), nullable=True),
sa.Column('typical_depth_cm', sa.Integer(), nullable=True),
sa.Column('source_name', sa.String(length=255), nullable=False),
sa.Column('source_url', sa.String(length=500), nullable=False),
sa.Column('confidence', sa.String(length=50), nullable=False),
sa.Column('geom', geoalchemy2.types.Geometry(geometry_type='POINT', srid=4326, dimension=2, from_text='ST_GeomFromEWKT', name='geometry', nullable=False), nullable=False),
sa.Column('matched_osm_way_id', sa.BigInteger(), nullable=True),
sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
sa.ForeignKeyConstraint(['matched_osm_way_id'], ['road_segments.osm_way_id'], ondelete='SET NULL'),
sa.PrimaryKeyConstraint('id')
)
sa.Table('hydrology_bulletin_events', metadata,
sa.Column('bulletin_sha256', sa.String(length=64), nullable=False),
sa.Column('station_id', sa.String(length=64), nullable=False),
sa.Column('event_date', sa.String(length=10), nullable=False),
sa.Column('data_type', sa.String(length=16), nullable=False),
sa.Column('event_kind', sa.String(length=16), nullable=False),
sa.Column('event_slot', sa.Integer(), nullable=False),
sa.Column('station_name', sa.String(length=64), nullable=False),
sa.Column('water_level_m', sa.Float(), nullable=True),
sa.Column('source_value', sa.String(length=32), nullable=False),
sa.Column('source_time', sa.String(length=32), nullable=False),
sa.Column('event_time', sa.DateTime(timezone=True), nullable=True),
sa.Column('missing_reason', sa.String(length=64), nullable=True),
sa.ForeignKeyConstraint(['bulletin_sha256'], ['hydrology_bulletins.content_sha256'], ),
sa.PrimaryKeyConstraint('bulletin_sha256', 'station_id', 'event_date', 'data_type', 'event_kind', 'event_slot')
)
sa.Table('road_edges', metadata,
sa.Column('osm_way_id', sa.BigInteger(), nullable=False),
sa.Column('edge_index', sa.Integer(), nullable=False),
sa.Column('geom', geoalchemy2.types.Geometry(geometry_type='LINESTRING', srid=4326, dimension=2, from_text='ST_GeomFromEWKT', name='geometry', nullable=False), nullable=False),
sa.Column('length_meters', sa.Float(), nullable=False),
sa.ForeignKeyConstraint(['osm_way_id'], ['road_segments.osm_way_id'], ondelete='CASCADE'),
sa.PrimaryKeyConstraint('osm_way_id', 'edge_index')
)
sa.Table('traffic_cameras', metadata,
sa.Column('cam_id', sa.String(length=64), nullable=False),
sa.Column('code', sa.String(length=64), nullable=True),
sa.Column('name', sa.String(length=255), nullable=False),
sa.Column('district', sa.String(length=128), nullable=True),
sa.Column('district_source', sa.String(length=255), nullable=True),
sa.Column('district_method', sa.String(length=64), nullable=True),
sa.Column('district_verified_at', sa.DateTime(timezone=True), nullable=True),
sa.Column('stream_url', sa.String(length=512), nullable=True),
sa.Column('nearest_osm_way_id', sa.BigInteger(), nullable=True),
sa.Column('geom', geoalchemy2.types.Geometry(geometry_type='POINT', srid=4326, dimension=2, from_text='ST_GeomFromEWKT', name='geometry'), nullable=True),
sa.Column('coordinate_source_url', sa.String(), nullable=True),
sa.Column('coordinate_verified_at', sa.DateTime(timezone=True), nullable=True),
sa.Column('source_uri', sa.String(length=512), nullable=True),
sa.Column('location_confidence', sa.String(length=64), nullable=True),
sa.Column('provider_snapshot_url', sa.String(length=512), nullable=True),
sa.Column('generated_source_url', sa.String(length=512), nullable=True),
sa.Column('orientation', sa.Integer(), nullable=True),
sa.Column('permitted_use', sa.String(length=64), nullable=True),
sa.Column('snapshot_cam_status', sa.String(length=32), nullable=True),
sa.Column('metadata_created_at', sa.DateTime(timezone=True), nullable=True),
sa.Column('metadata_modified_at', sa.DateTime(timezone=True), nullable=True),
sa.Column('bearing_degrees', sa.Float(), nullable=True),
sa.Column('field_of_view_degrees', sa.Float(), nullable=True),
sa.Column('view_verified_at', sa.DateTime(timezone=True), nullable=True),
sa.Column('view_verification_source_url', sa.String(), nullable=True),
sa.Column('line_of_sight_verified', sa.Boolean(), nullable=True),
sa.Column('observed_osm_way_id', sa.BigInteger(), nullable=True),
sa.Column('observed_edge_index', sa.Integer(), nullable=True),
sa.ForeignKeyConstraint(['nearest_osm_way_id'], ['road_segments.osm_way_id'], ondelete='SET NULL'),
sa.ForeignKeyConstraint(['observed_osm_way_id'], ['road_segments.osm_way_id'], ondelete='SET NULL'),
sa.PrimaryKeyConstraint('cam_id')
)
sa.Table('user_preferences', metadata,
sa.Column('user_id', sa.String(length=64), nullable=False),
sa.Column('transport_mode', sa.String(length=32), nullable=False),
sa.Column('avoid_flood_level', sa.String(length=32), nullable=False),
sa.Column('avoid_high_density', sa.Boolean(), nullable=False),
sa.Column('alert_notifications', sa.Boolean(), nullable=False),
sa.Column('voice_guidance_enabled', sa.Boolean(), nullable=False),
sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
sa.PrimaryKeyConstraint('user_id')
)
sa.Table('user_route_history', metadata,
sa.Column('id', sa.String(length=64), nullable=False),
sa.Column('user_id', sa.String(length=64), nullable=False),
sa.Column('origin_name', sa.String(length=255), nullable=False),
sa.Column('dest_name', sa.String(length=255), nullable=False),
sa.Column('origin_lat', sa.Float(), nullable=True),
sa.Column('origin_lng', sa.Float(), nullable=True),
sa.Column('dest_lat', sa.Float(), nullable=True),
sa.Column('dest_lng', sa.Float(), nullable=True),
sa.Column('distance_km', sa.Float(), nullable=False),
sa.Column('duration_mins', sa.Integer(), nullable=False),
sa.Column('travel_mode', sa.String(length=32), nullable=False),
sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
sa.PrimaryKeyConstraint('id')
)
sa.Table('user_saved_places', metadata,
sa.Column('id', sa.String(length=64), nullable=False),
sa.Column('user_id', sa.String(length=64), nullable=False),
sa.Column('name', sa.String(length=255), nullable=False),
sa.Column('address', sa.String(length=512), nullable=False),
sa.Column('lat', sa.Float(), nullable=False),
sa.Column('lng', sa.Float(), nullable=False),
sa.Column('category', sa.String(length=32), nullable=False),
sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
sa.PrimaryKeyConstraint('id')
)
sa.Table('camera_ingestion_state', metadata,
sa.Column('cam_id', sa.String(length=64), nullable=False),
sa.Column('source_status', sa.String(length=32), nullable=False),
sa.Column('last_attempt_at', sa.DateTime(timezone=True), nullable=True),
sa.Column('last_success_at', sa.DateTime(timezone=True), nullable=True),
sa.Column('last_captured_at', sa.DateTime(timezone=True), nullable=True),
sa.Column('last_retrieved_at', sa.DateTime(timezone=True), nullable=True),
sa.Column('next_retry_at', sa.DateTime(timezone=True), nullable=True),
sa.Column('failure_count', sa.Integer(), nullable=False),
sa.Column('http_status', sa.Integer(), nullable=True),
sa.Column('validation_status', sa.String(length=64), nullable=True),
sa.Column('image_hash', sa.String(length=64), nullable=True),
sa.Column('image_width', sa.Integer(), nullable=True),
sa.Column('image_height', sa.Integer(), nullable=True),
sa.Column('model_status', sa.String(length=64), nullable=True),
sa.Column('last_error_code', sa.String(length=256), nullable=True),
sa.Column('last_checked_url', sa.String(length=512), nullable=True),
sa.Column('requested_url', sa.Text(), nullable=True),
sa.Column('effective_url', sa.Text(), nullable=True),
sa.Column('chosen_variant', sa.String(length=32), nullable=True),
sa.Column('content_type', sa.String(length=64), nullable=True),
sa.Column('content_sha256', sa.String(length=64), nullable=True),
sa.Column('provider_id', sa.String(length=64), nullable=True),
sa.Column('cached_image_path', sa.String(length=256), nullable=True),
sa.Column('failure_reason', sa.Text(), nullable=True),
sa.Column('latest_snapshot_id', sa.String(length=64), nullable=True),
sa.Column('last_content_changed_at', sa.DateTime(timezone=True), nullable=True),
sa.Column('last_source_captured_at', sa.DateTime(timezone=True), nullable=True),
sa.ForeignKeyConstraint(['cam_id'], ['traffic_cameras.cam_id'], ondelete='CASCADE'),
sa.PrimaryKeyConstraint('cam_id')
)
sa.Table('camera_snapshots', metadata,
sa.Column('snapshot_id', sa.String(length=64), nullable=False),
sa.Column('camera_id', sa.String(length=64), nullable=False),
sa.Column('content_sha256', sa.String(length=64), nullable=False),
sa.Column('content_md5', sa.String(length=32), nullable=True),
sa.Column('file_path', sa.String(length=256), nullable=False),
sa.Column('file_size_bytes', sa.Integer(), nullable=False),
sa.Column('source_captured_at', sa.DateTime(timezone=True), nullable=True),
sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=False),
sa.Column('freshness_status', sa.String(length=32), nullable=False),
sa.Column('capture_time_status', sa.String(length=32), nullable=False),
sa.Column('inference_completed_at', sa.DateTime(timezone=True), nullable=True),
sa.Column('inference_input_sha256', sa.String(length=64), nullable=True),
sa.Column('overlay_path', sa.String(length=256), nullable=True),
sa.Column('enhanced_path', sa.String(length=256), nullable=True),
sa.Column('model_status', sa.String(length=64), nullable=True),
sa.Column('vehicle_count', sa.Integer(), nullable=True),
sa.Column('traffic_density_score', sa.Float(), nullable=True),
sa.Column('flood_ratio', sa.Float(), nullable=True),
sa.Column('is_latest', sa.Boolean(), nullable=False),
sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
sa.ForeignKeyConstraint(['camera_id'], ['traffic_cameras.cam_id'], ondelete='CASCADE'),
sa.PrimaryKeyConstraint('snapshot_id')
)

# Frozen indexes required by registry, history, and lookup queries.
sa.Index('ix_hcmc_district_boundaries_district_id', metadata.tables['hcmc_district_boundaries'].c['district_id'], unique=False)
sa.Index('ix_hcmc_district_boundaries_name', metadata.tables['hcmc_district_boundaries'].c['name'], unique=True)
sa.Index('ix_hydrology_bulletins_issued_at', metadata.tables['hydrology_bulletins'].c['issued_at'], unique=False)
sa.Index('ix_hydrology_observations_observed_at', metadata.tables['hydrology_observations'].c['observed_at'], unique=False)
sa.Index('ix_hydrology_observations_quality_status', metadata.tables['hydrology_observations'].c['quality_status'], unique=False)
sa.Index('ix_hydrology_observations_station_id', metadata.tables['hydrology_observations'].c['station_id'], unique=False)
sa.Index('ix_road_segments_is_flood_prone_history', metadata.tables['road_segments'].c['is_flood_prone_history'], unique=False)
sa.Index('ix_road_segments_osm_way_id', metadata.tables['road_segments'].c['osm_way_id'], unique=False)
sa.Index('ix_road_segments_street_name', metadata.tables['road_segments'].c['street_name'], unique=False)
sa.Index('ix_traffic_news_articles_canonical_url', metadata.tables['traffic_news_articles'].c['canonical_url'], unique=True)
sa.Index('ix_traffic_news_articles_category', metadata.tables['traffic_news_articles'].c['category'], unique=False)
sa.Index('ix_traffic_news_articles_id', metadata.tables['traffic_news_articles'].c['id'], unique=False)
sa.Index('ix_traffic_news_articles_published_at', metadata.tables['traffic_news_articles'].c['published_at'], unique=False)
sa.Index('ix_traffic_news_articles_source_name', metadata.tables['traffic_news_articles'].c['source_name'], unique=False)
sa.Index('ix_users_email', metadata.tables['users'].c['email'], unique=False)
sa.Index('ix_users_id', metadata.tables['users'].c['id'], unique=False)
sa.Index('ix_users_provider_account_id', metadata.tables['users'].c['provider_account_id'], unique=True)
sa.Index('ix_historical_flood_points_street_name', metadata.tables['historical_flood_points'].c['street_name'], unique=False)
sa.Index('ix_traffic_cameras_cam_id', metadata.tables['traffic_cameras'].c['cam_id'], unique=False)
sa.Index('ix_traffic_cameras_code', metadata.tables['traffic_cameras'].c['code'], unique=False)
sa.Index('ix_traffic_cameras_district', metadata.tables['traffic_cameras'].c['district'], unique=False)
sa.Index('ix_traffic_cameras_nearest_osm_way_id', metadata.tables['traffic_cameras'].c['nearest_osm_way_id'], unique=False)
sa.Index('ix_user_route_history_id', metadata.tables['user_route_history'].c['id'], unique=False)
sa.Index('ix_user_route_history_user_id', metadata.tables['user_route_history'].c['user_id'], unique=False)
sa.Index('ix_user_saved_places_id', metadata.tables['user_saved_places'].c['id'], unique=False)
sa.Index('ix_user_saved_places_user_id', metadata.tables['user_saved_places'].c['user_id'], unique=False)
sa.Index('ix_camera_ingestion_state_cam_id', metadata.tables['camera_ingestion_state'].c['cam_id'], unique=False)
sa.Index('ix_camera_ingestion_state_last_attempt_at', metadata.tables['camera_ingestion_state'].c['last_attempt_at'], unique=False)
sa.Index('ix_camera_ingestion_state_last_success_at', metadata.tables['camera_ingestion_state'].c['last_success_at'], unique=False)
sa.Index('ix_camera_ingestion_state_next_retry_at', metadata.tables['camera_ingestion_state'].c['next_retry_at'], unique=False)
sa.Index('ix_camera_ingestion_state_source_status', metadata.tables['camera_ingestion_state'].c['source_status'], unique=False)
sa.Index('ix_camera_snapshots_camera_id', metadata.tables['camera_snapshots'].c['camera_id'], unique=False)
sa.Index('ix_camera_snapshots_content_sha256', metadata.tables['camera_snapshots'].c['content_sha256'], unique=False)
sa.Index('ix_camera_snapshots_fetched_at', metadata.tables['camera_snapshots'].c['fetched_at'], unique=False)
sa.Index('ix_camera_snapshots_is_latest', metadata.tables['camera_snapshots'].c['is_latest'], unique=False)
sa.Index('ix_camera_snapshots_snapshot_id', metadata.tables['camera_snapshots'].c['snapshot_id'], unique=False)
