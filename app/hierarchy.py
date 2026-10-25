from typing import Any, Optional
from app.models import HierarchyNode, MeterHierarchy, HierarchyTreeNode


class HierarchyEngine:
    """
    Engine to parse, reconcile, heal anomalies in, and construct 
    distribution network topology trees from legacy meter data.
    """

    LEVELS = ["zone", "circle", "division", "subdivision", "substation", "feeder", "dt"]

    def __init__(self):
        # Canonical dictionaries per level: code -> canonical_name, and name -> canonical_code
        self.code_to_name: dict[str, dict[str, str]] = {lvl: {} for lvl in self.LEVELS}
        self.name_to_code: dict[str, dict[str, str]] = {lvl: {} for lvl in self.LEVELS}
        # Parent-child tracking: dt_code -> parent feeder, feeder_code -> parent substation, etc.
        self.parent_map: dict[str, dict[str, str]] = {lvl: {} for lvl in self.LEVELS}
        self.healed_count: int = 0
        self._is_indexed = False

    def build_indexes(self, meters: list[dict[str, Any]]) -> None:
        """Scan all meters to learn canonical codes, names, and relationships across the grid."""
        self.healed_count = 0
        for lvl in self.LEVELS:
            self.code_to_name[lvl].clear()
            self.name_to_code[lvl].clear()

        # Step 1: Collect all high-confidence pairs
        for meter in meters:
            h = meter.get("hierarchy") or {}
            for lvl in self.LEVELS:
                node = h.get(lvl)
                if isinstance(node, dict):
                    code = (node.get("code") or "").strip()
                    name = (node.get("name") or "").strip()
                    if code and name:
                        self.code_to_name[lvl][code] = name
                        self.name_to_code[lvl][name] = code

            # Also cross-reference DT code from root if present
            dt_code = meter.get("dtCode")
            dt_node = h.get("dt")
            if dt_code and isinstance(dt_node, dict) and dt_node.get("name"):
                self.code_to_name["dt"][dt_code] = dt_node["name"].strip()
                self.name_to_code["dt"][dt_node["name"].strip()] = dt_code

        self._is_indexed = True

    def heal_and_normalize(self, raw_hierarchy: dict[str, Any], meter_id: str = "") -> tuple[MeterHierarchy, bool]:
        """
        Normalize a raw meter hierarchy dictionary and heal any missing or empty fields.
        Returns the typed MeterHierarchy and a boolean indicating if any field was healed.
        """
        normalized_nodes = {}
        was_any_healed = False

        for lvl in self.LEVELS:
            node = raw_hierarchy.get(lvl)
            code = ""
            name = ""
            is_healed = False

            if isinstance(node, dict):
                code = (node.get("code") or "").strip()
                name = (node.get("name") or "").strip()
            elif isinstance(node, str) and node:
                name = node.strip()

            # Attempt healing if code or name is missing
            if not code and name:
                # Look up code from name
                canonical_code = self.name_to_code[lvl].get(name)
                if canonical_code:
                    code = canonical_code
                    is_healed = True
                else:
                    # Synthesize from name pattern e.g. "Circle 6" -> "C-06"
                    synthesized = self._synthesize_code(lvl, name)
                    if synthesized:
                        code = synthesized
                        is_healed = True
                    else:
                        code = f"UNKNOWN-{name}"
                        is_healed = True

            elif code and not name:
                # Look up name from code
                canonical_name = self.code_to_name[lvl].get(code)
                if canonical_name:
                    name = canonical_name
                    is_healed = True
                else:
                    synthesized = self._synthesize_name(lvl, code)
                    if synthesized:
                        name = synthesized
                        is_healed = True
                    else:
                        name = f"Unknown {lvl.capitalize()} ({code})"
                        is_healed = True

            elif not code and not name:
                code = f"UNKNOWN-{lvl.upper()}"
                name = f"Unknown {lvl.capitalize()}"
                is_healed = True

            if is_healed:
                was_any_healed = True
                self.healed_count += 1

            normalized_nodes[lvl] = HierarchyNode(
                code=code,
                name=name,
                is_healed=is_healed
            )

        meter_hierarchy = MeterHierarchy(
            zone=normalized_nodes["zone"],
            circle=normalized_nodes["circle"],
            division=normalized_nodes["division"],
            subdivision=normalized_nodes["subdivision"],
            substation=normalized_nodes["substation"],
            feeder=normalized_nodes["feeder"],
            dt=normalized_nodes["dt"]
        )
        return meter_hierarchy, was_any_healed

    def _synthesize_code(self, level: str, name: str) -> Optional[str]:
        """Synthesize standard code from name if known pattern matches."""
        name_lower = name.lower()
        if "circle" in name_lower:
            # "Circle 5" -> "C-05"
            parts = name.split()
            if len(parts) >= 2 and parts[-1].isdigit():
                return f"C-{int(parts[-1]):02d}"
        elif "feeder" in name_lower:
            # "Feeder 5" -> "F-005"
            parts = name.split()
            if len(parts) >= 2 and parts[-1].isdigit():
                return f"F-{int(parts[-1]):03d}"
        elif "substation" in name_lower:
            parts = name.split()
            if len(parts) >= 2 and parts[-1].isdigit():
                return f"SS-{int(parts[-1]):02d}"
        return None

    def _synthesize_name(self, level: str, code: str) -> Optional[str]:
        """Synthesize standard name from code if known pattern matches."""
        code_upper = code.upper()
        if code_upper.startswith("C-"):
            num = code_upper.replace("C-", "").lstrip("0")
            return f"Circle {num}"
        elif code_upper.startswith("F-"):
            num = code_upper.replace("F-", "").lstrip("0")
            return f"Feeder {num}"
        elif code_upper.startswith("SS-"):
            num = code_upper.replace("SS-", "").lstrip("0")
            return f"Substation {num}"
        return None

    def build_tree(self, meters: list[dict[str, Any]], root_level: Optional[str] = None, root_code: Optional[str] = None) -> list[HierarchyTreeNode]:
        """
        Reconstruct the full 7-tier grid hierarchy into a nested tree structure.
        Optionally filter by root_level and root_code (e.g. root_level='zone', root_code='Z-01').
        """
        # Multi-level aggregation
        # Zone -> Circle -> Division -> Subdivision -> Substation -> Feeder -> DT
        root_nodes: dict[str, dict[str, Any]] = {}

        for meter in meters:
            h = meter.get("hierarchy") or {}
            norm_h, _ = self.heal_and_normalize(h, meter.get("meterId", ""))

            # Chain:
            levels = [
                ("zone", norm_h.zone.code, norm_h.zone.name),
                ("circle", norm_h.circle.code, norm_h.circle.name),
                ("division", norm_h.division.code, norm_h.division.name),
                ("subdivision", norm_h.subdivision.code, norm_h.subdivision.name),
                ("substation", norm_h.substation.code, norm_h.substation.name),
                ("feeder", norm_h.feeder.code, norm_h.feeder.name),
                ("dt", norm_h.dt.code, norm_h.dt.name),
            ]

            curr_dict = root_nodes
            for lvl, code, name in levels:
                if code not in curr_dict:
                    curr_dict[code] = {
                        "code": code,
                        "name": name,
                        "level": lvl,
                        "meter_count": 0,
                        "children": {}
                    }
                curr_dict[code]["meter_count"] += 1
                curr_dict = curr_dict[code]["children"]

        def dict_to_tree_node(d: dict[str, Any]) -> HierarchyTreeNode:
            children_nodes = [
                dict_to_tree_node(child) for child in d["children"].values()
            ]
            # Sort children by code
            children_nodes.sort(key=lambda x: x.code)
            return HierarchyTreeNode(
                code=d["code"],
                name=d["name"],
                level=d["level"],
                meter_count=d["meter_count"],
                children=children_nodes
            )

        full_tree = [dict_to_tree_node(v) for v in root_nodes.values()]
        full_tree.sort(key=lambda x: x.code)

        if not root_level or not root_code:
            return full_tree

        # Filter by root_level and root_code
        def find_subtree(nodes: list[HierarchyTreeNode]) -> list[HierarchyTreeNode]:
            matches = []
            for n in nodes:
                if n.level.lower() == root_level.lower() and n.code.lower() == root_code.lower():
                    matches.append(n)
                else:
                    sub_matches = find_subtree(n.children)
                    matches.extend(sub_matches)
            return matches

        return find_subtree(full_tree)
