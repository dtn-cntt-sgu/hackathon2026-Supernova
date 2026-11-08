"""Conservative directed polyline overlap for HCMC traffic-flow observations."""
import math
from shapely.geometry import LineString
from shapely.ops import unary_union
from shapely import STRtree


def observed_fraction(route_coordinates, flow_lines, tolerance_m=12.0):
    """Fraction of route length within aligned source segments, excluding endpoint extrapolation.

    Coordinates are [longitude, latitude]. Disconnected provider links stay separate.
    shortcut: a local equirectangular projection is adequate for city corridors;
    use a regional CRS before extending this matcher to intercontinental geometry.
    """
    try:
        lon0, lat0 = map(float, route_coordinates[0][:2])
        scale_x = 111_195.0 * math.cos(math.radians(lat0))

        def projected(coordinates):
            points = []
            for point in coordinates:
                lon, lat = map(float, point[:2])
                if not math.isfinite(lon) or not math.isfinite(lat) or not -180 <= lon <= 180 or not -85 <= lat <= 85:
                    raise ValueError("Invalid traffic geometry")
                points.append(((lon-lon0)*scale_x, (lat-lat0)*111_195.0))
            return points

        route = projected(route_coordinates)
        if len(route) < 2:
            return 0.0
        length = LineString(route).length
        if not length:
            return 0.0
        route_pieces = [LineString([a,b]) for a,b in zip(route, route[1:]) if a != b]
        tree = STRtree(route_pieces)
        covered = {}
        cosine_limit = math.cos(math.radians(30))
        for flow_coordinates in flow_lines:
            flow = projected(flow_coordinates)
            for fa, fb in zip(flow, flow[1:]):
                fdx, fdy = fb[0]-fa[0], fb[1]-fa[1]
                flen = math.hypot(fdx, fdy)
                if flen <= 0:
                    continue
                source = LineString([fa, fb])
                corridor = source.buffer(tolerance_m, cap_style=2)
                for index in tree.query(corridor):
                    route_piece = route_pieces[index]
                    ra, rb = route_piece.coords
                    rdx, rdy = rb[0]-ra[0], rb[1]-ra[1]
                    rlen = math.hypot(rdx, rdy)
                    if rlen <= 0 or (rdx*fdx+rdy*fdy)/(rlen*flen) < cosine_limit:
                        continue
                    overlap = route_piece.intersection(corridor)
                    if not overlap.is_empty:
                        covered.setdefault(int(index), []).append(overlap)
        # Union provider overlaps per traversal; repeated visits to a road still count.
        covered_length = sum(unary_union(parts).length for parts in covered.values())
        return min(1.0, max(0.0, covered_length / length))
    except (TypeError, ValueError, IndexError, OverflowError):
        return 0.0


def valid_confidence(value):
    if isinstance(value, bool):
        return None
    try:
        confidence = float(value)
        return confidence if math.isfinite(confidence) and .3 <= confidence <= 1 else None
    except (TypeError, ValueError):
        return None


def cached_record(record, now, ttl):
    """Old/malformed/missing timestamps cannot acquire a new observation age."""
    from datetime import datetime
    if not isinstance(record, dict) or not isinstance(record.get("payload"), dict):
        return None
    try:
        timestamp = datetime.fromisoformat(record["cached_at"])
        if timestamp.tzinfo is None or not 0 <= (now-timestamp).total_seconds() <= ttl:
            return None
        return record["payload"], timestamp
    except (KeyError, TypeError, ValueError):
        return None
