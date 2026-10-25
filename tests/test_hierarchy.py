import pytest
from app.hierarchy import HierarchyEngine


def test_hierarchy_healing():
    engine = HierarchyEngine()
    
    # Sample meters with both complete and incomplete data
    sample_meters = [
        {
            "meterId": "J100001",
            "hierarchy": {
                "zone": {"name": "Jaipur Zone 1", "code": "Z-01"},
                "circle": {"name": "Circle 1", "code": "C-01"},
                "division": {"name": "Division 1", "code": "D-01"},
                "subdivision": {"name": "Subdivision 1", "code": "SD-01"},
                "substation": {"name": "Substation 1", "code": "SS-01"},
                "feeder": {"name": "Feeder 1", "code": "F-001"},
                "dt": {"name": "Malviya Nagar DT 1", "code": "DT-001"},
            }
        },
        # Anomaly 1: circle has name but empty code
        {
            "meterId": "J100011",
            "hierarchy": {
                "zone": {"name": "Jaipur Zone 1", "code": "Z-01"},
                "circle": {"name": "Circle 6", "code": ""},
                "division": {"name": "Division 1", "code": "D-01"},
                "subdivision": {"name": "Subdivision 1", "code": "SD-01"},
                "substation": {"name": "Substation 1", "code": "SS-01"},
                "feeder": {"name": "Feeder 1", "code": "F-001"},
                "dt": {"name": "Malviya Nagar DT 1", "code": "DT-001"},
            }
        },
        # Anomaly 2: feeder has code but empty name
        {
            "meterId": "J100162",
            "hierarchy": {
                "zone": {"name": "Jaipur Zone 1", "code": "Z-01"},
                "circle": {"name": "Circle 1", "code": "C-01"},
                "division": {"name": "Division 1", "code": "D-01"},
                "subdivision": {"name": "Subdivision 1", "code": "SD-01"},
                "substation": {"name": "Substation 1", "code": "SS-01"},
                "feeder": {"name": "", "code": "F-003"},
                "dt": {"name": "Malviya Nagar DT 1", "code": "DT-001"},
            }
        }
    ]

    engine.build_indexes(sample_meters)

    # Test healing for J100011
    h11 = sample_meters[1]["hierarchy"]
    norm11, healed11 = engine.heal_and_normalize(h11, "J100011")
    assert healed11 is True
    assert norm11.circle.code == "C-06"
    assert norm11.circle.name == "Circle 6"
    assert norm11.circle.is_healed is True

    # Test healing for J100162
    h162 = sample_meters[2]["hierarchy"]
    norm162, healed162 = engine.heal_and_normalize(h162, "J100162")
    assert healed162 is True
    assert norm162.feeder.code == "F-003"
    assert norm162.feeder.name == "Feeder 3"
    assert norm162.feeder.is_healed is True


def test_build_hierarchy_tree():
    engine = HierarchyEngine()
    sample_meters = [
        {
            "meterId": "J100001",
            "hierarchy": {
                "zone": {"name": "Jaipur Zone 1", "code": "Z-01"},
                "circle": {"name": "Circle 1", "code": "C-01"},
                "division": {"name": "Division 1", "code": "D-01"},
                "subdivision": {"name": "Subdivision 1", "code": "SD-01"},
                "substation": {"name": "Substation 1", "code": "SS-01"},
                "feeder": {"name": "Feeder 1", "code": "F-001"},
                "dt": {"name": "Malviya Nagar DT 1", "code": "DT-001"},
            }
        },
        {
            "meterId": "J100002",
            "hierarchy": {
                "zone": {"name": "Jaipur Zone 1", "code": "Z-01"},
                "circle": {"name": "Circle 1", "code": "C-01"},
                "division": {"name": "Division 1", "code": "D-01"},
                "subdivision": {"name": "Subdivision 1", "code": "SD-01"},
                "substation": {"name": "Substation 1", "code": "SS-01"},
                "feeder": {"name": "Feeder 1", "code": "F-001"},
                "dt": {"name": "Malviya Nagar DT 1", "code": "DT-001"},
            }
        }
    ]

    engine.build_indexes(sample_meters)
    tree = engine.build_tree(sample_meters)
    assert len(tree) == 1
    root = tree[0]
    assert root.code == "Z-01"
    assert root.level == "zone"
    assert root.meter_count == 2
    assert len(root.children) == 1
