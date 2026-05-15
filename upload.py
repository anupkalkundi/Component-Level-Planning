import streamlit as st
import pandas as pd
import re
import math


# =========================================================
# VARIABLE ALIASES
# =========================================================
VARIABLE_ALIASES = {

    # HEIGHT / LENGTH
    "opening_length": "opening_height",
    "height_opening": "opening_height",

    # WIDTH
    "opening_w": "opening_width",

    # CLEARANCE
    "clr": "clearance",

    # ALLOWANCE
    "extra_width": "allowance",
    "extra_length": "allowance",

    # FRAME
    "vertical_length": "frame_vertical_length",
    "horizontal_length": "frame_horizontal_length"
}


# =========================================================
# NORMALIZE VARIABLE
# =========================================================
def normalize_variable(var_name):

    var_name = str(var_name).strip()

    return VARIABLE_ALIASES.get(
        var_name,
        var_name
    )


# =========================================================
# NORMALIZE FORMULA
# =========================================================
def normalize_formula(formula):

    if not formula:
        return formula

    formula = str(formula)

    for old, new in VARIABLE_ALIASES.items():

        formula = re.sub(
            rf"\b{old}\b",
            new,
            formula
        )

    return formula


# =========================================================
# EXTRACT VARIABLES
# =========================================================
def extract_formula_variables(formula):

    if not formula:
        return []

    ignore_words = {
        "abs",
        "min",
        "max",
        "round",
        "math"
    }

    variables = re.findall(
        r"\b[A-Za-z_][A-Za-z0-9_]*\b",
        str(formula)
    )

    cleaned = []

    for v in variables:

        if v not in ignore_words:

            cleaned.append(
                normalize_variable(v)
            )

    return sorted(list(set(cleaned)))


# =========================================================
# SAFE FORMULA EVALUATOR
# =========================================================
def evaluate_formula(
    formula,
    variables
):

    formula = normalize_formula(formula)

    allowed_names = {
        "abs": abs,
        "min": min,
        "max": max,
        "round": round,
        "math": math
    }

    allowed_names.update(variables)

    return eval(
        formula,
        {"__builtins__": {}},
        allowed_names
    )


# =========================================================
# GET REQUIRED INPUTS
# =========================================================
def get_required_inputs(rules_df):

    all_variables = set()

    for formula in rules_df["formula_used"].dropna():

        vars_found = extract_formula_variables(
            formula
        )

        for var in vars_found:
            all_variables.add(var)

    calculated_attributes = set()

    for attr in rules_df["attribute"].dropna():

        calculated_attributes.add(
            normalize_variable(attr)
        )

    required_inputs = sorted(
        list(
            all_variables - calculated_attributes
        )
    )

    return required_inputs


# =========================================================
# RESOLVE FORMULAS RECURSIVELY
# =========================================================
def resolve_formulas(
    rules_df,
    user_inputs
):

    calculated = {}

    # =========================================
    # SAVE USER INPUTS
    # =========================================
    for k, v in user_inputs.items():

        calculated[
            normalize_variable(k)
        ] = v

    results = []

    pending = rules_df.to_dict("records")

    iteration = 0

    max_iterations = 100

    while pending and iteration < max_iterations:

        iteration += 1

        unresolved = []

        progress = False

        for rule in pending:

            try:

                component = str(
                    rule["component"]
                ).strip()

                attribute = normalize_variable(
                    rule["attribute"]
                )

                rule_type = str(
                    rule["type"]
                ).lower().strip()

                formula = normalize_formula(
                    rule.get("formula_used")
                )

                quantity = rule.get("quantity")

                # =====================================
                # FIXED RULE
                # =====================================
                if rule_type == "fixed":

                    value = float(quantity)

                # =====================================
                # MANUAL RULE
                # =====================================
                elif rule_type == "manual":

                    if attribute not in calculated:

                        unresolved.append(rule)
                        continue

                    value = calculated[attribute]

                # =====================================
                # FORMULA RULE
                # =====================================
                elif rule_type == "formula":

                    required = extract_formula_variables(
                        formula
                    )

                    missing = [
                        var
                        for var in required
                        if var not in calculated
                    ]

                    if missing:

                        unresolved.append(rule)
                        continue

                    value = evaluate_formula(
                        formula,
                        calculated
                    )

                else:

                    unresolved.append(rule)
                    continue

                # =====================================
                # SAVE RESULTS
                # =====================================
                result_key = (
                    f"{component}_{attribute}"
                )

                calculated[result_key] = value

                calculated[attribute] = value

                results.append({

                    "Component": component,
                    "Attribute": attribute,
                    "Type": rule_type,
                    "Formula": formula,
                    "Value": round(value, 2)
                })

                progress = True

            except Exception as e:

                unresolved.append(rule)

        if not progress:
            break

        pending = unresolved

    return results, pending, calculated


# =========================================================
# MAIN COMPONENT CALCULATOR PAGE
# =========================================================
def show_component_calculator(conn):

    st.title("Component Calculator")

    st.markdown(
        """
        This page follows the flow:

        Project → Unit → House → Product → Inputs →
        Rule Engine → Generated Components → Tracking
        """
    )

    # =====================================================
    # LOAD RULES
    # =====================================================
    query = """
        SELECT
            product_cat,
            product_code,
            component,
            attribute,
            type,
            formula_used,
            quantity
        FROM product_component_rules
    """

    rules_df = pd.read_sql(query, conn)

    if rules_df.empty:
        st.warning("No component rules found.")
        return

    # =====================================================
    # PROJECTS
    # =====================================================
    projects = pd.read_sql(
        "SELECT DISTINCT project_name FROM projects",
        conn
    )["project_name"].tolist()

    selected_project = st.selectbox(
        "Project",
        projects
    )

    # =====================================================
    # UNIT TYPES
    # =====================================================
    units = pd.read_sql(
        f"""
        SELECT DISTINCT unit_type
        FROM unit_types
        WHERE project_name = '{selected_project}'
        """,
        conn
    )["unit_type"].tolist()

    selected_unit = st.selectbox(
        "Unit Type",
        units
    )

    # =====================================================
    # HOUSES
    # =====================================================
    houses = pd.read_sql(
        f"""
        SELECT DISTINCT house_number
        FROM houses
        WHERE project_name = '{selected_project}'
        AND unit_type = '{selected_unit}'
        """,
        conn
    )["house_number"].tolist()

    selected_house = st.selectbox(
        "House Number",
        houses
    )

    # =====================================================
    # PRODUCTS
    # =====================================================
    products = pd.read_sql(
        """
        SELECT DISTINCT product_code
        FROM products
        """,
        conn
    )["product_code"].tolist()

    selected_product = st.selectbox(
        "Product",
        products
    )

    # =====================================================
    # FILTER RULES
    # =====================================================
    filtered_rules = rules_df[
        rules_df["product_code"] == selected_product
    ].copy()

    if filtered_rules.empty:
        st.error("No rules found.")
        return

    # =====================================================
    # FORMULA INPUTS
    # =====================================================
    st.subheader("Formula Inputs")

    required_inputs = get_required_inputs(
        filtered_rules
    )

    user_inputs = {}

    cols = st.columns(4)

    for idx, variable in enumerate(required_inputs):

        with cols[idx % 4]:

            user_inputs[variable] = st.number_input(
                variable,
                value=0.0,
                step=1.0,
                key=variable
            )

    # =====================================================
    # GENERATE BUTTON
    # =====================================================
    if st.button(
        "Generate Components",
        type="primary"
    ):

        results, pending, calculated = resolve_formulas(
            filtered_rules,
            user_inputs
        )

        # =================================================
        # GENERATED COMPONENTS
        # =================================================
        st.subheader("Generated Component Preview")

        if results:

            result_df = pd.DataFrame(results)

            st.dataframe(
                result_df,
                use_container_width=True,
                hide_index=True
            )

        else:

            st.warning("No components generated.")

        # =================================================
        # UNRESOLVED RULES
        # =================================================
        if pending:

            st.subheader("Unresolved Rules")

            for rule in pending:

                formula = rule.get("formula_used")

                missing = []

                if formula:

                    required = extract_formula_variables(
                        formula
                    )

                    missing = [
                        var
                        for var in required
                        if var not in calculated
                    ]

                st.error(
                    f"{rule['component']} / "
                    f"{rule['attribute']} → "
                    f"Missing variables: "
                    f"{', '.join(missing)}"
                )

        # =================================================
        # DEBUG VARIABLES
        # =================================================
        st.subheader("Calculated Variables")

        st.json(calculated)


