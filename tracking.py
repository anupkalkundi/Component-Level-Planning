def show_tracking(conn, cur):
    import streamlit as st
    import pandas as pd
    from psycopg2.extras import execute_values

    st.title("🏭 Component Production Tracker")

    # =========================================================
    # CONNECTION CHECK
    # =========================================================
    try:
        if conn.closed != 0:
            st.error("Database connection lost. Please refresh once.")
            return
    except Exception:
        st.error("Database connection issue. Please refresh.")
        return

    # =========================================================
    # SETUP TABLES
    # =========================================================
    def ensure_tracking_tables():
        cur.execute("""
            CREATE TABLE IF NOT EXISTS generated_components (
                id SERIAL PRIMARY KEY,
                project_name TEXT,
                unit_type TEXT,
                house_number TEXT,
                product_cat TEXT,
                product_code TEXT,
                orientation TEXT,
                component TEXT,
                attribute TEXT,
                value NUMERIC,
                quantity INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS component_stages (
                stage_id SERIAL PRIMARY KEY,
                stage_name TEXT UNIQUE,
                sequence INTEGER
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS component_tracking_log (
                id SERIAL PRIMARY KEY,
                generated_component_id INTEGER,
                stage_id INTEGER,
                status TEXT,
                quantity INTEGER,
                timestamp TIMESTAMP DEFAULT NOW()
            )
        """)

        stages = [
            ("Raw Wood Cutting", 1),
            ("Hydraulic Composer", 2),
            ("Panel Saw", 3),
            ("Sanding", 4),
            ("CNC", 5),
            ("Sent To Pre-Assembly", 6),
        ]
        
        cur.execute("""
            DELETE FROM component_stages
            WHERE stage_name NOT IN (
                'Raw Wood Cutting',
                'Hydraulic Composer',
                'Panel Saw',
                'Sanding',
                'CNC',
                'Sent To Pre-Assembly'
            )
        """)
                
        execute_values(
            cur,
            """
            INSERT INTO component_stages
            (stage_name, sequence)
            VALUES %s
            ON CONFLICT (stage_name)
            DO UPDATE SET sequence = EXCLUDED.sequence
            """,
            stages
        )

        conn.commit()

    ensure_tracking_tables()

    # =========================================================
    # DATA FUNCTIONS
    # =========================================================
    @st.cache_data(ttl=300)
    def get_projects():
        cur.execute("""
            SELECT DISTINCT project_name
            FROM generated_components
            WHERE project_name IS NOT NULL
            ORDER BY project_name
        """)
        return [r[0] for r in cur.fetchall()]

    @st.cache_data(ttl=300)
    def get_units(projects_tuple):
        projects = list(projects_tuple)

        if projects:
            cur.execute("""
                SELECT DISTINCT unit_type
                FROM generated_components
                WHERE project_name = ANY(%s)
                AND unit_type IS NOT NULL
                ORDER BY unit_type
            """, (projects,))
        else:
            cur.execute("""
                SELECT DISTINCT unit_type
                FROM generated_components
                WHERE unit_type IS NOT NULL
                ORDER BY unit_type
            """)

        return [r[0] for r in cur.fetchall()]

    @st.cache_data(ttl=300)
    def get_houses(projects_tuple, units_tuple):
        projects = list(projects_tuple)
        units = list(units_tuple)

        query = """
            SELECT DISTINCT house_number
            FROM generated_components
            WHERE 1=1
        """

        params = []

        if projects:
            query += " AND project_name = ANY(%s)"
            params.append(projects)

        if units:
            query += " AND unit_type = ANY(%s)"
            params.append(units)

        query += " AND house_number IS NOT NULL ORDER BY house_number"

        cur.execute(query, params)
        return [r[0] for r in cur.fetchall()]

    @st.cache_data(ttl=300)
    def get_product_categories(projects_tuple, units_tuple, houses_tuple):
        projects = list(projects_tuple)
        units = list(units_tuple)
        houses = list(houses_tuple)

        query = """
            SELECT DISTINCT product_cat
            FROM generated_components
            WHERE 1=1
        """

        params = []

        if projects:
            query += " AND project_name = ANY(%s)"
            params.append(projects)

        if units:
            query += " AND unit_type = ANY(%s)"
            params.append(units)

        if houses:
            query += " AND house_number = ANY(%s)"
            params.append(houses)

        query += " AND product_cat IS NOT NULL ORDER BY product_cat"

        cur.execute(query, params)
        return [r[0] for r in cur.fetchall()]

    @st.cache_data(ttl=300)
    def get_product_codes(projects_tuple, units_tuple, houses_tuple, cats_tuple):
        projects = list(projects_tuple)
        units = list(units_tuple)
        houses = list(houses_tuple)
        cats = list(cats_tuple)

        query = """
            SELECT DISTINCT product_code
            FROM generated_components
            WHERE 1=1
        """

        params = []

        if projects:
            query += " AND project_name = ANY(%s)"
            params.append(projects)

        if units:
            query += " AND unit_type = ANY(%s)"
            params.append(units)

        if houses:
            query += " AND house_number = ANY(%s)"
            params.append(houses)

        if cats:
            query += " AND product_cat = ANY(%s)"
            params.append(cats)

        query += " AND product_code IS NOT NULL ORDER BY product_code"

        cur.execute(query, params)
        return [r[0] for r in cur.fetchall()]

    @st.cache_data(ttl=300)
    def get_components(
        projects_tuple,
        units_tuple,
        houses_tuple,
        cats_tuple,
        codes_tuple
    ):
        projects = list(projects_tuple)
        units = list(units_tuple)
        houses = list(houses_tuple)
        cats = list(cats_tuple)
        codes = list(codes_tuple)

        query = """
            SELECT DISTINCT component
            FROM generated_components
            WHERE 1=1
        """

        params = []

        if projects:
            query += " AND project_name = ANY(%s)"
            params.append(projects)

        if units:
            query += " AND unit_type = ANY(%s)"
            params.append(units)

        if houses:
            query += " AND house_number = ANY(%s)"
            params.append(houses)

        if cats:
            query += " AND product_cat = ANY(%s)"
            params.append(cats)

        if codes:
            query += " AND product_code = ANY(%s)"
            params.append(codes)

        query += " AND component IS NOT NULL ORDER BY component"

        cur.execute(query, params)
        return [r[0] for r in cur.fetchall()]

    @st.cache_data(ttl=300)
    def get_stages():
        cur.execute("""
            SELECT stage_name
            FROM component_stages
            ORDER BY sequence
        """)
        return [r[0] for r in cur.fetchall()]

    def get_filtered_generated_components(
        projects,
        units,
        houses,
        cats,
        codes,
        components
    ):
        query = """
            SELECT
                id,
                project_name,
                unit_type,
                house_number,
                product_cat,
                product_code,
                COALESCE(orientation, '') AS orientation,
                component,
                attribute,
                calculated_value,
                COALESCE(quantity, 1) AS quantity
            FROM generated_components
            WHERE 1=1
        """

        params = []

        if projects:
            query += " AND project_name = ANY(%s)"
            params.append(projects)

        if units:
            query += " AND unit_type = ANY(%s)"
            params.append(units)

        if houses:
            query += " AND house_number = ANY(%s)"
            params.append(houses)

        if cats:
            query += " AND product_cat = ANY(%s)"
            params.append(cats)

        if codes:
            query += " AND product_code = ANY(%s)"
            params.append(codes)

        if components:
            query += " AND component = ANY(%s)"
            params.append(components)

        query += """
            ORDER BY
                project_name,
                unit_type,
                house_number,
                product_code,
                component,
                attribute
        """

        cur.execute(query, params)
        return cur.fetchall()

    # =========================================================
    # FILTERS - MULTIPLE SELECTION
    # =========================================================
    st.markdown("### 🔎 Select Generated Components")

    row1_col1, row1_col2, row1_col3 = st.columns(3)

    with row1_col1:
        project_options = get_projects()
        selected_projects = st.multiselect(
            "Project",
            project_options
        )

    with row1_col2:
        unit_options = get_units(tuple(selected_projects))
        selected_units = st.multiselect(
            "Unit Type",
            unit_options
        )

    with row1_col3:
        house_options = get_houses(
            tuple(selected_projects),
            tuple(selected_units)
        )
        selected_houses = st.multiselect(
            "House Number",
            house_options
        )

    row2_col1, row2_col2, row2_col3 = st.columns(3)

    with row2_col1:
        product_cat_options = get_product_categories(
            tuple(selected_projects),
            tuple(selected_units),
            tuple(selected_houses)
        )
        selected_product_cats = st.multiselect(
            "Product Type",
            product_cat_options
        )

    with row2_col2:
        product_code_options = get_product_codes(
            tuple(selected_projects),
            tuple(selected_units),
            tuple(selected_houses),
            tuple(selected_product_cats)
        )
        selected_product_codes = st.multiselect(
            "Product Code",
            product_code_options
        )

    with row2_col3:
        component_options = get_components(
            tuple(selected_projects),
            tuple(selected_units),
            tuple(selected_houses),
            tuple(selected_product_cats),
            tuple(selected_product_codes)
        )
        selected_components = st.multiselect(
            "Component",
            component_options
        )

    # =========================================================
    # FETCH COMPONENTS
    # =========================================================
    rows = get_filtered_generated_components(
        selected_projects,
        selected_units,
        selected_houses,
        selected_product_cats,
        selected_product_codes,
        selected_components
    )

    if not rows:
        st.warning("No generated components found")
        return

    df = pd.DataFrame(
        rows,
        columns=[
            "generated_component_id",
            "project_name",
            "unit_type",
            "house_number",
            "product_cat",
            "product_code",
            "orientation",
            "component",
            "attribute",
            "value",
            "quantity"
        ]
    )

    df["display"] = (
        df["house_number"].astype(str)
        + " • "
        + df["product_code"].astype(str)
        + " • "
        + df["component"].astype(str)
        + " • "
        + df["attribute"].astype(str)
        + " • Qty "
        + df["quantity"].astype(str)
    )

    search_text = st.text_input("🔍 Filter Components")

    if search_text:
        df = df[
            df["display"].str.contains(
                search_text,
                case=False,
                na=False
            )
        ]

    if df.empty:
        st.warning("No components match your filter")
        return

    select_all = st.checkbox("Select All Visible Components")
    df["Select"] = select_all

    with st.expander("📦 Component Selection Table", expanded=False):
        edited_df = st.data_editor(
            df[["Select", "display"]],
            use_container_width=True,
            hide_index=True,
            height=320,
            key="component_selection_editor"
        )

    selected_rows = edited_df[
        edited_df["Select"] == True
    ]

    if selected_rows.empty:
        st.info("Select components to continue")
        return

    selected_ids = df.loc[
        selected_rows.index,
        "generated_component_id"
    ].tolist()

    st.success(f"{len(selected_ids)} component row(s) selected")

    # =========================================================
    # LATEST STAGE
    # =========================================================
    stage_sequence = get_stages()

    cur.execute("""
        WITH latest_stage AS (
            SELECT
                t.generated_component_id,
                s.stage_name,
                t.status,
                t.quantity,
                ROW_NUMBER() OVER (
                    PARTITION BY t.generated_component_id
                    ORDER BY t.timestamp DESC, t.id DESC
                ) AS rn
            FROM component_tracking_log t
            JOIN component_stages s
            ON t.stage_id = s.stage_id
            WHERE t.generated_component_id = ANY(%s)
        )
        SELECT
            generated_component_id,
            stage_name,
            status,
            quantity
        FROM latest_stage
        WHERE rn = 1
    """, (selected_ids,))

    latest_data = cur.fetchall()

    if latest_data:
        latest_df = pd.DataFrame(
            latest_data,
            columns=[
                "generated_component_id",
                "stage",
                "status",
                "tracked_quantity"
            ]
        )
    else:
        latest_df = pd.DataFrame(
            columns=[
                "generated_component_id",
                "stage",
                "status",
                "tracked_quantity"
            ]
        )

    missing_ids = set(selected_ids) - set(
        latest_df["generated_component_id"].tolist()
    )

    if missing_ids:
        extra = pd.DataFrame({
            "generated_component_id": list(missing_ids),
            "stage": ["Not Started"] * len(missing_ids),
            "status": ["Not Started"] * len(missing_ids),
            "tracked_quantity": [0] * len(missing_ids)
        })

        latest_df = pd.concat(
            [latest_df, extra],
            ignore_index=True
        )

    matrix_df = df[
        df["generated_component_id"].isin(selected_ids)
    ].copy()

    matrix_df = matrix_df.merge(
        latest_df,
        on="generated_component_id",
        how="left"
    )

    matrix_df["stage"] = matrix_df["stage"].fillna("Not Started")
    matrix_df["status"] = matrix_df["status"].fillna("Not Started")

    if stage_sequence:
        last_stage_name = stage_sequence[-1]

        matrix_df.loc[
            (matrix_df["stage"] == last_stage_name)
            & (matrix_df["status"] == "Completed"),
            "stage"
        ] = "Completed"

    # =========================================================
    # CURRENT LIVE STAGES
    # =========================================================
    st.markdown("### 📍 Current Live Stages Found")

    available_stages = []
    stage_counts = {}

    for stage_name in ["Not Started"] + stage_sequence + ["Completed"]:
        count = len(
            matrix_df[
                matrix_df["stage"] == stage_name
            ]
        )

        if count > 0:
            available_stages.append(stage_name)
            stage_counts[stage_name] = count

    if not available_stages:
        st.warning("No stage data found")
        return

    stage_cols = st.columns(len(available_stages))

    for index, stage_name in enumerate(available_stages):
        if stage_cols[index].button(
            f"{stage_name} ({stage_counts[stage_name]})",
            use_container_width=True
        ):
            st.session_state["component_inspect_stage"] = stage_name

    inspect_stage = st.session_state.get(
        "component_inspect_stage",
        available_stages[0]
    )

    stage_group = matrix_df[
        matrix_df["stage"] == inspect_stage
    ].copy()

    st.info(f"Inspecting: {inspect_stage}")

    stage_search = st.text_input(
        f"🔎 Search inside {inspect_stage}",
        key="component_stage_search"
    )

    if stage_search:
        stage_group = stage_group[
            stage_group["display"].str.contains(
                stage_search,
                case=False,
                na=False
            )
        ]

    if stage_group.empty:
        st.warning("No components in selected stage")
        return

    select_stage_all = st.checkbox(
        f"Select All Visible in {inspect_stage}",
        key="component_stage_select_all"
    )

    shown_rows = stage_group[
        [
            "generated_component_id",
            "display",
            "quantity",
            "status"
        ]
    ].copy()

    shown_rows["Move"] = select_stage_all

    edited_stage = st.data_editor(
        shown_rows[
            [
                "Move",
                "display",
                "quantity",
                "status"
            ]
        ],
        use_container_width=True,
        hide_index=True,
        key="component_stage_move_editor"
    )

    chosen = edited_stage[
        edited_stage["Move"] == True
    ]

    if chosen.empty:
        return

    move_ids = shown_rows.loc[
        chosen.index,
        "generated_component_id"
    ].tolist()

    current_stage = inspect_stage
    current_status = stage_group.iloc[0]["status"]

    if current_stage == "Not Started":
        next_stage = stage_sequence[0]
    else:
        try:
            stage_index = stage_sequence.index(current_stage)
            next_stage = stage_sequence[stage_index + 1]
        except Exception:
            next_stage = "Completed"

    col4, col5 = st.columns(2)

    col4.info(f"Current Stage: {current_stage} ({current_status})")
    col5.success(f"Next Allowed Stage: {next_stage}")

    movement_type = st.radio(
        "Movement Type",
        [
            "Normal Forward Move",
            "Rework / Send Back"
        ],
        horizontal=True,
        key="component_movement_selector"
    )

    # =========================================================
    # UPDATE FORM
    # =========================================================
    with st.form(f"component_tracking_update_form_{movement_type}"):

        if movement_type == "Normal Forward Move":

            selected_stage = st.selectbox(
                "Move Selected Components To Stage",
                stage_sequence
            )

            status = st.selectbox(
                "Update Status",
                [
                    "In Progress",
                    "Completed"
                ]
            )

        else:

            if current_stage == "Not Started":
                allowed_stage_options = ["Not Started"]
            else:
                try:
                    idx = stage_sequence.index(current_stage)
                    allowed_stage_options = (
                        ["Not Started"] + stage_sequence[:idx]
                    )
                except Exception:
                    allowed_stage_options = ["Not Started"]

            selected_stage = st.selectbox(
                "Move Selected Components To Stage",
                allowed_stage_options
            )

            status = st.selectbox(
                "Update Status",
                ["In Progress"]
            )

            rework_reason = st.selectbox(
                "Rework Reason",
                [
                    "Dimension Issue",
                    "Material Issue",
                    "Cutting Defect",
                    "CNC Error",
                    "Surface Damage",
                    "Assembly Mismatch",
                    "QC Failed",
                    "Other"
                ]
            )

            rework_note = st.text_input(
                "Type Reason (Optional)"
            )

        update_quantity = st.number_input(
            "Quantity",
            min_value=1,
            value=1,
            step=1
        )

        submitted = st.form_submit_button(
            "Update Selected"
        )

    # =========================================================
    # UPDATE LOGIC
    # =========================================================
    if submitted:

        if movement_type == "Normal Forward Move":

            if current_status == "In Progress":

                if not (
                    selected_stage == current_stage
                    and status == "Completed"
                ):
                    st.error(
                        "Complete current stage first before moving ahead"
                    )
                    return

            elif current_status == "Completed":

                if (
                    selected_stage != next_stage
                    and not (
                        current_stage == stage_sequence[-1]
                        and selected_stage == current_stage
                    )
                ):
                    st.error("Invalid stage movement")
                    return

        else:

            if selected_stage == current_stage:
                st.error(
                    "Rework stage cannot be same as current"
                )
                return

        with st.spinner("Updating selected components..."):

            try:
                if (
                    movement_type == "Rework / Send Back"
                    and selected_stage == "Not Started"
                ):

                    cur.execute("""
                        DELETE FROM component_tracking_log
                        WHERE generated_component_id = ANY(%s)
                    """, (move_ids,))

                    conn.commit()

                    if "component_inspect_stage" in st.session_state:
                        del st.session_state["component_inspect_stage"]

                    st.success(
                        f"{len(move_ids)} component row(s) reset to Not Started"
                    )

                    st.rerun()

                cur.execute("""
                    SELECT stage_id
                    FROM component_stages
                    WHERE stage_name = %s
                """, (selected_stage,))

                stage_result = cur.fetchone()

                if not stage_result:
                    st.error(f"Stage not found: {selected_stage}")
                    return

                stage_id = stage_result[0]

                data = []

                for component_id in move_ids:

                    data.append((
                        component_id,
                        stage_id,
                        status,
                        int(update_quantity)
                    ))

                    if (
                        movement_type == "Normal Forward Move"
                        and selected_stage == current_stage
                        and status == "Completed"
                    ):

                        if current_stage in stage_sequence:

                            idx = stage_sequence.index(current_stage)

                            if idx + 1 < len(stage_sequence):

                                next_stage_name = stage_sequence[idx + 1]

                                cur.execute("""
                                    SELECT stage_id
                                    FROM component_stages
                                    WHERE stage_name = %s
                                """, (next_stage_name,))

                                auto_next_stage_id = cur.fetchone()[0]

                                data.append((
                                    component_id,
                                    auto_next_stage_id,
                                    "In Progress",
                                    int(update_quantity)
                                ))

                execute_values(
                    cur,
                    """
                    INSERT INTO component_tracking_log
                    (
                        generated_component_id,
                        stage_id,
                        status,
                        quantity,
                        timestamp
                    )
                    VALUES %s
                    """,
                    data,
                    template="(%s, %s, %s, %s, NOW())"
                )

                conn.commit()

                if "component_inspect_stage" in st.session_state:
                    del st.session_state["component_inspect_stage"]

                st.success(
                    f"{len(move_ids)} component row(s) updated successfully"
                )

                st.rerun()

            except Exception as e:
                try:
                    conn.rollback()
                except Exception:
                    pass

                st.error(f"Update failed: {e}")
