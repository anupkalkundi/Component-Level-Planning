def show_delete(conn, cur):
    import streamlit as st

    if st.session_state.get("role") != "admin":
        st.error("Access denied")
        st.stop()

    st.title("Delete Master Data")

    # =========================================================
    # HELPERS
    # =========================================================

    def safe_execute(query, params=None):
        try:
            cur.execute(query, params or ())
        except Exception as e:
            conn.rollback()
            raise e

    def fetch_all(query, params=None):
        safe_execute(query, params)
        return cur.fetchall()

    def sql_placeholders(values):
        return ",".join(["%s"] * len(values))

    def delete_unused_products():
        safe_execute("""
            DELETE FROM products p
            WHERE NOT EXISTS (
                SELECT 1
                FROM product_component_rules r
                WHERE r.product_cat = p.product_cat
                AND r.product_code = p.product_code
            )
        """)

    # =========================================================
    # DELETE TYPE
    # =========================================================

    delete_type = st.radio(
        "Delete Level",
        [
            "Project",
            "Unit Type",
            "House",
            "Product",
            "Formula"
        ]
    )

    confirm = st.checkbox("I confirm this delete action")

    # =========================================================
    # PROJECT DELETE - MULTIPLE
    # =========================================================

    if delete_type == "Project":

        projects = fetch_all("""
            SELECT project_name
            FROM projects
            ORDER BY project_name
        """)

        project_names = [p[0] for p in projects]

        if not project_names:
            st.warning("No projects found")
            return

        selected_projects = st.multiselect(
            "Projects",
            project_names
        )

        st.warning(
            "This will delete selected projects, their unit types, and houses."
        )

        if st.button("Delete Selected Projects"):
            if not confirm:
                st.warning("Please confirm delete action")
                return

            if not selected_projects:
                st.warning("Please select projects")
                return

            try:
                placeholders = sql_placeholders(selected_projects)

                safe_execute(f"""
                    DELETE FROM houses
                    WHERE project_name IN ({placeholders})
                """, selected_projects)

                safe_execute(f"""
                    DELETE FROM unit_types
                    WHERE project_name IN ({placeholders})
                """, selected_projects)

                safe_execute(f"""
                    DELETE FROM projects
                    WHERE project_name IN ({placeholders})
                """, selected_projects)

                conn.commit()

                st.success(
                    f"{len(selected_projects)} project(s) deleted successfully"
                )

                st.rerun()

            except Exception as e:
                conn.rollback()
                st.error(f"Project delete failed: {e}")

    # =========================================================
    # UNIT TYPE DELETE - MULTIPLE
    # =========================================================

    elif delete_type == "Unit Type":

        projects = fetch_all("""
            SELECT project_name
            FROM projects
            ORDER BY project_name
        """)

        project_names = [p[0] for p in projects]

        if not project_names:
            st.warning("No projects found")
            return

        selected_project = st.selectbox(
            "Project",
            project_names
        )

        units = fetch_all("""
            SELECT unit_type
            FROM unit_types
            WHERE project_name = %s
            ORDER BY unit_type
        """, (selected_project,))

        unit_types = [u[0] for u in units]

        if not unit_types:
            st.warning("No unit types found")
            return

        selected_units = st.multiselect(
            "Unit Types",
            unit_types
        )

        st.warning(
            "This will delete selected unit types and their houses."
        )

        if st.button("Delete Selected Unit Types"):
            if not confirm:
                st.warning("Please confirm delete action")
                return

            if not selected_units:
                st.warning("Please select unit types")
                return

            try:
                placeholders = sql_placeholders(selected_units)

                safe_execute(f"""
                    DELETE FROM houses
                    WHERE project_name = %s
                    AND unit_type IN ({placeholders})
                """, [selected_project] + selected_units)

                safe_execute(f"""
                    DELETE FROM unit_types
                    WHERE project_name = %s
                    AND unit_type IN ({placeholders})
                """, [selected_project] + selected_units)

                conn.commit()

                st.success(
                    f"{len(selected_units)} unit type(s) deleted successfully"
                )

                st.rerun()

            except Exception as e:
                conn.rollback()
                st.error(f"Unit type delete failed: {e}")

    # =========================================================
    # HOUSE DELETE - MULTIPLE
    # =========================================================

    elif delete_type == "House":

        projects = fetch_all("""
            SELECT project_name
            FROM projects
            ORDER BY project_name
        """)

        project_names = [p[0] for p in projects]

        if not project_names:
            st.warning("No projects found")
            return

        selected_project = st.selectbox(
            "Project",
            project_names
        )

        units = fetch_all("""
            SELECT unit_type
            FROM unit_types
            WHERE project_name = %s
            ORDER BY unit_type
        """, (selected_project,))

        unit_types = [u[0] for u in units]

        if not unit_types:
            st.warning("No unit types found")
            return

        selected_unit = st.selectbox(
            "Unit Type",
            unit_types
        )

        houses = fetch_all("""
            SELECT house_number
            FROM houses
            WHERE project_name = %s
            AND unit_type = %s
            ORDER BY house_number
        """, (
            selected_project,
            selected_unit
        ))

        house_numbers = [h[0] for h in houses]

        if not house_numbers:
            st.warning("No houses found")
            return

        selected_houses = st.multiselect(
            "House Numbers",
            house_numbers
        )

        if st.button("Delete Selected Houses"):
            if not confirm:
                st.warning("Please confirm delete action")
                return

            if not selected_houses:
                st.warning("Please select houses")
                return

            try:
                placeholders = sql_placeholders(selected_houses)

                safe_execute(f"""
                    DELETE FROM houses
                    WHERE project_name = %s
                    AND unit_type = %s
                    AND house_number IN ({placeholders})
                """, [selected_project, selected_unit] + selected_houses)

                conn.commit()

                st.success(
                    f"{len(selected_houses)} house(s) deleted successfully"
                )

                st.rerun()

            except Exception as e:
                conn.rollback()
                st.error(f"House delete failed: {e}")

    # =========================================================
    # PRODUCT DELETE - MULTIPLE
    # =========================================================

    elif delete_type == "Product":

        products = fetch_all("""
            SELECT DISTINCT product_cat, product_code
            FROM products
            ORDER BY product_cat, product_code
        """)

        if not products:
            st.warning("No products found")
            return

        product_dict = {
            f"{p[0]} | {p[1]}": (p[0], p[1])
            for p in products
        }

        selected_products = st.multiselect(
            "Products",
            list(product_dict.keys())
        )

        delete_rules_too = st.checkbox(
            "Also delete component formula rules for selected products",
            value=True
        )

        st.warning(
            "This will delete selected product master records. "
            "If enabled, related component formulas will also be deleted."
        )

        if st.button("Delete Selected Products"):
            if not confirm:
                st.warning("Please confirm delete action")
                return

            if not selected_products:
                st.warning("Please select products")
                return

            try:
                deleted_products = 0
                deleted_rules = 0

                for product_label in selected_products:
                    product_cat, product_code = product_dict[product_label]

                    if delete_rules_too:
                        safe_execute("""
                            DELETE FROM product_component_rules
                            WHERE product_cat = %s
                            AND product_code = %s
                        """, (
                            product_cat,
                            product_code
                        ))

                        deleted_rules += cur.rowcount

                    safe_execute("""
                        DELETE FROM products
                        WHERE product_cat = %s
                        AND product_code = %s
                    """, (
                        product_cat,
                        product_code
                    ))

                    deleted_products += cur.rowcount

                conn.commit()

                st.success(f"""
Deleted successfully

Products deleted: {deleted_products}
Formula rules deleted: {deleted_rules}
""")

                st.rerun()

            except Exception as e:
                conn.rollback()
                st.error(f"Product delete failed: {e}")

    # =========================================================
    # FORMULA DELETE - MULTIPLE PRODUCTS + MULTIPLE RULES
    # =========================================================

    elif delete_type == "Formula":

        products = fetch_all("""
            SELECT DISTINCT product_cat, product_code
            FROM product_component_rules
            ORDER BY product_cat, product_code
        """)

        if not products:
            st.warning("No formula rules found")
            return

        product_dict = {
            f"{p[0]} | {p[1]}": (p[0], p[1])
            for p in products
        }

        selected_products = st.multiselect(
            "Products",
            list(product_dict.keys())
        )

        if not selected_products:
            st.info("Select one or more products to view formula rules.")
            return

        selected_product_pairs = [
            product_dict[p]
            for p in selected_products
        ]

        rule_rows = []

        for product_cat, product_code in selected_product_pairs:
            rows = fetch_all("""
                SELECT
                    product_cat,
                    product_code,
                    component,
                    attribute,
                    type,
                    formula_used,
                    quantity
                FROM product_component_rules
                WHERE product_cat = %s
                AND product_code = %s
                ORDER BY component, attribute
            """, (
                product_cat,
                product_code
            ))

            rule_rows.extend(rows)

        if not rule_rows:
            st.warning("No formula rules found for selected products")
            return

        rule_dict = {}

        for index, rule in enumerate(rule_rows):
            product_cat = rule[0]
            product_code = rule[1]
            component = rule[2]
            attribute = rule[3]
            rule_type = rule[4]
            formula_used = rule[5]
            quantity = rule[6]

            label = (
                f"{product_cat} | {product_code} | "
                f"{component} | {attribute} | {rule_type} | "
                f"{formula_used or ''} | Qty: {quantity}"
            )

            rule_dict[label] = index

        selected_rules = st.multiselect(
            "Formula / Component Rules",
            list(rule_dict.keys())
        )

        delete_all_rules_for_selected_products = st.checkbox(
            "Delete all formula rules for selected products",
            value=False
        )

        delete_empty_products = st.checkbox(
            "Delete product master if no formula rules remain",
            value=False
        )

        if delete_all_rules_for_selected_products:
            st.warning(
                "All component rules for the selected products will be deleted."
            )

        if st.button("Delete Formula Rules"):
            if not confirm:
                st.warning("Please confirm delete action")
                return

            if (
                not delete_all_rules_for_selected_products
                and not selected_rules
            ):
                st.warning("Please select formula rules")
                return

            try:
                deleted_count = 0

                if delete_all_rules_for_selected_products:

                    for product_cat, product_code in selected_product_pairs:
                        safe_execute("""
                            DELETE FROM product_component_rules
                            WHERE product_cat = %s
                            AND product_code = %s
                        """, (
                            product_cat,
                            product_code
                        ))

                        deleted_count += cur.rowcount

                else:

                    for label in selected_rules:
                        rule = rule_rows[rule_dict[label]]

                        safe_execute("""
                            DELETE FROM product_component_rules
                            WHERE product_cat = %s
                            AND product_code = %s
                            AND component = %s
                            AND attribute = %s
                            AND type = %s
                            AND COALESCE(formula_used, '') = COALESCE(%s, '')
                            AND COALESCE(quantity, -1) = COALESCE(%s, -1)
                        """, (
                            rule[0],
                            rule[1],
                            rule[2],
                            rule[3],
                            rule[4],
                            rule[5],
                            rule[6]
                        ))

                        deleted_count += cur.rowcount

                if delete_empty_products:
                    delete_unused_products()

                conn.commit()

                st.success(
                    f"{deleted_count} formula rule(s) deleted successfully"
                )

                st.rerun()

            except Exception as e:
                conn.rollback()
                st.error(f"Formula delete failed: {e}")
