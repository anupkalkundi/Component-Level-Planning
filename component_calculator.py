import streamlit as st
import pandas as pd
import re
from decimal import Decimal
from psycopg2.extras import execute_values


class FormulaError(Exception):
    pass


VARIABLE_ALIASES = {
    "opening_height": "opening_length",
    "opening_l": "opening_length",
    "opening_w": "opening_width",
    "height_opening": "opening_length",
    "width_opening": "opening_width",
    "clearance": "vertical_clearance",
    "clr": "vertical_clearance",
    "v_clearance": "vertical_clearance",
    "h_clearance": "horizontal_clearance",
    "extra_l": "architrave_extra_length",
    "extra_length": "architrave_extra_length",
    "extra_w": "architrave_extra_width",
    "extra_width": "architrave_extra_width",
    "frame_h_thk": "frame_horizontal_thickness",
    "frame_v_thk": "frame_vertical_thickness",
    "frame_horizontal_thicknes": "frame_horizontal_thickness",
    "glass_shutter_width_top1": "glass_shutter_width_top_1",
    "glass_shutter_width_top2": "glass_shutter_width_top_2",
    "glass_shutter_width_bottom1": "glass_shutter_width_bottom_1",
    "glass_shutter_width_bottom2": "glass_shutter_width_bottom_2",
}


def sanitize_formula(formula_str: str) -> str:
    """
    Sanitizes formula strings by replacing custom syntax with python-compatible math syntax.
    """
    if not formula_str or pd.isna(formula_str):
        return ""
    f = str(formula_str).strip()
    f = re.sub(r"\bx\b", "*", f, flags=re.IGNORECASE)
    f = f.replace("=", "")
    return f.strip()


def resolve_and_evaluate(comp_name, formulas_dict, context_vars, tracking_cache, visited=None):
    """
    Recursively resolves formulas by identifying and evaluating dependencies first.
    Prevents circular references and safeguards name variations.
    """
    if visited is None:
        visited = set()

    # If already calculated in this run, return it
    if comp_name in tracking_cache:
        return tracking_cache[comp_name]

    if comp_name in visited:
        # Circular dependency protection fallback
        return Decimal("0")

    visited.add(comp_name)
    raw_formula = formulas_dict[comp_name]
    sanitized = sanitize_formula(raw_formula)

    # Base variables (from user inputs) should be replaced with word boundary precision
    for base_var, base_val in context_vars.items():
        pattern = rf"\b{re.escape(base_var)}\b"
        sanitized = re.sub(pattern, str(base_val), sanitized)

    # Check for references to OTHER component formulas in this product group
    for other_comp in formulas_dict.keys():
        if other_comp == comp_name:
            continue
        
        # Word boundary match ensuring 'glass_shutter_width' doesn't flag 'glass_shutter_width_top_1'
        pattern = rf"\b{re.escape(other_comp)}\b"
        if re.search(pattern, sanitized):
            # Recursively resolve the dependency first
            dep_value = resolve_and_evaluate(other_comp, formulas_dict, context_vars, tracking_cache, visited)
            sanitized = re.sub(pattern, str(dep_value), sanitized)

    # Run clean mathematical evaluations safely
    try:
        # Strip out alphabetic characters remaining to prevent execution issues
        clean_expr = re.sub(r"[A-Za-z_]+", "", sanitized)
        clean_expr = clean_expr.strip()
        if not clean_expr:
            result = Decimal("0")
        else:
            # Basic mathematical safety cleaning
            clean_expr = re.sub(r"\s+", "", clean_expr)
            result = Decimal(str(eval(clean_expr)))
    except Exception:
        result = Decimal("0")

    tracking_cache[comp_name] = result
    return result


def parse_component_formulas(conn, selected_project, selected_unit_type, selected_house):
    """
    Fetches details from the database and runs the calculation framework cleanly
    """
    try:
        with conn.cursor() as cur:
            # 1. Fetch specifications mapping
            cur.execute(
                """
                SELECT product_cat, product_code, opening_length, opening_width, 
                       vertical_clearance, horizontal_clearance, architrave_extra_length, 
                       architrave_extra_width, frame_horizontal_thickness, frame_vertical_thickness
                FROM physical_specifications
                WHERE project_name = %s AND unit_type = %s AND house_number = %s
            """,
                (selected_project, selected_unit_type, selected_house),
            )
            spec_rows = cur.fetchall()
            if not spec_rows:
                st.warning("No physical specifications found for selection.")
                return

            # Map results cleanly
            specs = []
            for r in spec_rows:
                specs.append({
                    "product_cat": r[0],
                    "product_code": r[1],
                    "opening_length": Decimal(str(r[2] or 0)),
                    "opening_width": Decimal(str(r[3] or 0)),
                    "vertical_clearance": Decimal(str(r[4] or 0)),
                    "horizontal_clearance": Decimal(str(r[5] or 0)),
                    "architrave_extra_length": Decimal(str(r[6] or 0)),
                    "architrave_extra_width": Decimal(str(r[7] or 0)),
                    "frame_horizontal_thickness": Decimal(str(r[8] or 0)),
                    "frame_vertical_thickness": Decimal(str(r[9] or 0)),
                })

            generated_insert_rows = []
            tracking_insert_rows = []

            # Process each category independently
            for spec in specs:
                prod_cat = spec["product_cat"]
                prod_code = spec["product_code"]

                # Get all matching formula schema parameters
                cur.execute(
                    """
                    SELECT component, attribute, formula, width, thickness, qty, orientation
                    FROM component_formulas
                    WHERE product_category = %s AND product_code = %s
                """,
                    (prod_cat, prod_code),
                )
                formula_rows = cur.fetchall()
                if not formula_rows:
                    continue

                # Isolate formulas for this current specific block loop execution
                formulas_dict = {}
                rows_metadata = []

                for fr in formula_rows:
                    comp = str(fr[0]).strip()
                    attr = str(fr[1]).strip()
                    form = str(fr[2] or "").strip()
                    
                    # Create unique tracking identifier keys per attribute row requirement
                    lookup_key = f"{comp}_{attr}".strip()
                    formulas_dict[lookup_key] = form
                    
                    rows_metadata.append({
                        "component": comp,
                        "attribute": attr,
                        "lookup_key": lookup_key,
                        "width": Decimal(str(fr[3] or 0)),
                        "thickness": Decimal(str(fr[4] or 0)),
                        "qty": int(fr[5] or 1),
                        "orientation": str(fr[6] or ""),
                    })

                # Base runtime evaluation execution variables
                context_vars = {
                    "opening_length": spec["opening_length"],
                    "opening_width": spec["opening_width"],
                    "vertical_clearance": spec["vertical_clearance"],
                    "horizontal_clearance": spec["horizontal_clearance"],
                    "architrave_extra_length": spec["architrave_extra_length"],
                    "architrave_extra_width": spec["architrave_extra_width"],
                    "frame_horizontal_thickness": spec["frame_horizontal_thickness"],
                    "frame_vertical_thickness": spec["frame_vertical_thickness"],
                }

                # Apply mapping variable aliases cleanly across validation blocks
                for alias_key, standard_name in VARIABLE_ALIASES.items():
                    if standard_name in context_vars:
                        context_vars[alias_key] = context_vars[standard_name]

                # Run recursive calculations using tracking caches
                tracking_cache = {}
                for l_key in formulas_dict.keys():
                    resolve_and_evaluate(l_key, formulas_dict, context_vars, tracking_cache)

                # Format processed calculations structural maps directly into compilation lists
                for meta in rows_metadata:
                    lookup_key = meta["lookup_key"]
                    calculated_val = tracking_cache.get(lookup_key, Decimal("0"))

                    # Compute extra parameter dependencies safely
                    w_val = meta["width"]
                    t_val = meta["thickness"]
                    q_val = meta["qty"]
                    
                    cft_val = Decimal("0")
                    if calculated_val > 0 and w_val > 0 and t_val > 0:
                        # Standard volumetric CFT formulation values calculation
                        cft_val = (calculated_val * w_val * t_val) / Decimal("144")

                    generated_insert_rows.append((
                        selected_project,
                        selected_unit_type,
                        selected_house,
                        prod_cat,
                        prod_code,
                        meta["component"],
                        meta["attribute"],
                        float(calculated_val),
                        float(w_val),
                        float(t_val),
                        float(cft_val),
                        meta["orientation"],
                        q_val,
                    ))

                    # Track components on length values attributes solely
                    if meta["attribute"].lower() == "length":
                        tracking_insert_rows.append((
                            selected_project,
                            selected_house,
                            meta["component"],
                            q_val,
                            0,
                            q_val,
                            "Pending",
                        ))

            if not generated_insert_rows:
                st.info("No formula calculations completed for this combination selection.")
                return

            # Wipe old instances tracking entries clean to prevent duplicates duplication crashes
            cur.execute(
                """
                DELETE FROM generated_components 
                WHERE project_name = %s AND unit_type = %s AND house_number = %s
            """,
                (selected_project, selected_unit_type, selected_house),
            )

            for item in tracking_insert_rows:
                cur.execute(
                    """
                    DELETE FROM tracking 
                    WHERE project_name = %s AND house_number = %s AND component = %s
                """,
                    (selected_project, selected_house, item[2]),
                )

            # Mass inserts processing updates
            execute_values(
                cur,
                """
                INSERT INTO generated_components
                (project_name, unit_type, house_number, product_cat, product_code, 
                 component, attribute, calculated_value, width, thickness, cft, orientation, qty)
                VALUES %s
                """,
                generated_insert_rows,
            )

            execute_values(
                cur,
                """
                INSERT INTO tracking
                (project_name, house_number, component, required_qty, completed_qty, pending_qty, status)
                VALUES %s
                """,
                tracking_insert_rows,
            )

            conn.commit()
            st.success(f"{len(generated_insert_rows)} component(s) processed and updated successfully!")

    except Exception as e:
        conn.rollback()
        st.error(f"Failed to calculate and store components: {e}")
