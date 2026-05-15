import re
import pandas as pd
import streamlit as st


# =========================================================
# SAFE FORMULA EVALUATION
# =========================================================
def safe_eval_formula(formula, context):
    """
    Safely evaluate formula using available variables
    """

    allowed_names = {
        k: float(v)
        for k, v in context.items()
        if v is not None and str(v) != ""
    }

    return eval(
        formula,
        {"__builtins__": {}},
        allowed_names
    )


# =========================================================
# EXTRACT VARIABLES
# =========================================================
def extract_formula_variables(formula):

    if formula is None:
        return []

    ignore_words = {
        "abs",
        "max",
        "min",
        "round"
    }

    variables = re.findall(
        r"\b[A-Za-z_][A-Za-z0-9_]*\b",
        str(formula)
    )

    return sorted(
        set(v for v in variables if v not in ignore_words)
    )


# =========================================================
# NORMALIZE VARIABLE NAME
# =========================================================
def normalize_name(value):

    return str(value) \
        .strip() \
        .lower() \
        .replace(" ", "_")


# =========================================================
# GET REQUIRED MANUAL INPUTS
# =========================================================
def get_required_manual_inputs(rules_df):

    calculated_outputs = set()

    # =============================================
    # FIND GENERATED VARIABLES
    # =============================================
    for _, row in rules_df.iterrows():

        component = normalize_name(row["component"])
        attribute = normalize_name(row["attribute"])

        output_name = f"{component}_{attribute}"

        calculated_outputs.add(output_name)

    # =============================================
    # FIND ALL VARIABLES USED IN FORMULAS
    # =============================================
    all_formula_variables = set()

    for _, row in rules_df.iterrows():

        formula = row.get("formula_used")

        if pd.isna(formula):
            continue

        variables = extract_formula_variables(formula)

        for variable in variables:
            all_formula_variables.add(variable)

    # =============================================
    # TRUE MANUAL INPUTS
    # =============================================
    manual_inputs = sorted(
        all_formula_variables - calculated_outputs
    )

    return manual_inputs


# =========================================================
# MAIN ENGINE
# =========================================================
def run_component_engine(rules_df, user_inputs):

    calculation_context = {}

    # =============================================
    # LOAD USER INPUTS
    # =============================================
    for key, value in user_inputs.items():

        calculation_context[key] = value

    generated_components = []

    errors = []

    # =============================================
    # ITERATIVE SOLVER
    # =============================================
    pending_rules = rules_df.copy()

    max_iterations = 100

    iteration = 0

    while not pending_rules.empty and iteration < max_iterations:

        solved_in_this_iteration = []

        for idx, row in pending_rules.iterrows():

            component = str(row["component"]).strip()

            attribute = str(row["attribute"]).strip()

            rule_type = normalize_name(row["type"])

            formula = row.get("formula_used")

            quantity = row.get("quantity", 1)

            output_name = normalize_name(
                f"{component}_{attribute}"
            )

            try:

                # =====================================
                # FIXED VALUE
                # =====================================
                if rule_type == "fixed":

                    result = quantity

                # =====================================
                # MANUAL VALUE
                # =====================================
                elif rule_type == "manual":

                    input_name = normalize_name(attribute)

                    if input_name not in calculation_context:
                        raise Exception(
                            f"Missing manual input: {input_name}"
                        )

                    result = calculation_context[input_name]

                # =====================================
                # FORMULA VALUE
                # =====================================
                elif rule_type == "formula":

                    variables = extract_formula_variables(formula)

                    missing = [
                        v for v in variables
                        if v not in calculation_context
                    ]

                    # Wait until next iteration
                    if missing:
                        continue

                    result = safe_eval_formula(
                        formula,
                        calculation_context
                    )

                else:

                    raise Exception(
                        f"Unknown rule type: {rule_type}"
                    )

                # =====================================
                # SAVE RESULT INTO CONTEXT
                # =====================================
                calculation_context[output_name] = result

                generated_components.append({
                    "Component": component,
                    "Attribute": attribute,
                    "Type": rule_type,
                    "Formula": formula,
                    "Value": result
                })

                solved_in_this_iteration.append(idx)

            except Exception as e:

                errors.append(
                    f"{component} / {attribute}: {str(e)}"
                )

        # =========================================
        # REMOVE SOLVED RULES
        # =========================================
        pending_rules = pending_rules.drop(solved_in_this_iteration)

        # =========================================
        # STOP IF DEADLOCK
        # =========================================
        if not solved_in_this_iteration:
            break

        iteration += 1

    # =============================================
    # FINAL UNSOLVED RULES
    # =============================================
    if not pending_rules.empty:

        for _, row in pending_rules.iterrows():

            component = row["component"]
            attribute = row["attribute"]
            formula = row.get("formula_used")

            variables = extract_formula_variables(formula)

            missing = [
                v for v in variables
                if v not in calculation_context
            ]

            errors.append(
                f"{component} / {attribute}: "
                f"Missing variables: {', '.join(missing)}"
            )

    return generated_components, errors, calculation_context


# =========================================================
# MAIN STREAMLIT PAGE
# =========================================================
def show_component_calculator(rules_df):

    st.title("Component Calculator")

    st.markdown(
        "This page follows the flow:<br>"
        "Project → Unit → House → Product → Inputs → Rule Engine → Generated Components → Tracking",
        unsafe_allow_html=True
    )

    st.divider()

    # =====================================================
    # REQUIRED INPUTS
    # =====================================================
    st.subheader("Formula Inputs")

    required_inputs = get_required_manual_inputs(rules_df)

    user_inputs = {}

    cols = st.columns(4)

    for i, variable in enumerate(required_inputs):

        with cols[i % 4]:

            default_value = 0.0

            # =========================================
            # OPTIONAL DEFAULTS
            # =========================================
            default_map = {
                "clearance": 20.0,
                "extra_width": 60.0,
                "extra_length": 60.0,
                "allowance": 11.0,
                "groove": 8.0,
                "cut": 7.0,
                "offset": 22.0
            }

            if variable in default_map:
                default_value = default_map[variable]

            value = st.number_input(
                variable,
                value=float(default_value),
                step=1.0,
                key=variable
            )

            user_inputs[variable] = value

    st.divider()

    # =====================================================
    # RUN ENGINE
    # =====================================================
    generated_components, errors, context = run_component_engine(
        rules_df,
        user_inputs
    )

    # =====================================================
    # ERRORS
    # =====================================================
    st.subheader("Generated Component Preview")

    if errors:

        for error in errors:
            st.error(error)

    # =====================================================
    # GENERATED COMPONENTS
    # =====================================================
    if generated_components:

        preview_df = pd.DataFrame(generated_components)

        st.dataframe(
            preview_df,
            use_container_width=True,
            hide_index=True
        )

    else:

        st.warning("No components generated")

    # =====================================================
    # SAVE BUTTON
    # =====================================================
    st.button(
        "Save Generated Components",
        type="primary"
    )

    # =====================================================
    # DEBUG CONTEXT
    # =====================================================
    with st.expander("Calculation Context"):

        context_df = pd.DataFrame([
            {
                "Variable": k,
                "Value": v
            }
            for k, v in context.items()
        ])

        st.dataframe(
            context_df,
            use_container_width=True,
            hide_index=True
        )


# =========================================================
# SAMPLE TEST DATA
# =========================================================
# REMOVE THIS WHEN USING DATABASE
# =========================================================
if __name__ == "__main__":

    sample_rules = pd.DataFrame([

        {
            "component": "Frame Vertical",
            "attribute": "length",
            "type": "formula",
            "formula_used": "opening_length-clearance",
            "quantity": None
        },

        {
            "component": "Frame Horizontal",
            "attribute": "length",
            "type": "formula",
            "formula_used": "opening_width-clearance",
            "quantity": None
        },

        {
            "component": "Architrave Horizontal",
            "attribute": "length",
            "type": "formula",
            "formula_used": "opening_width+extra_width",
            "quantity": None
        },

        {
            "component": "Architrave Vertical",
            "attribute": "length",
            "type": "formula",
            "formula_used": "opening_length+extra_length",
            "quantity": None
        },

        {
            "component": "Flush Shutter",
            "attribute": "length",
            "type": "formula",
            "formula_used": "frame_vertical_length-frame_horizontal_thickness+allowance-groove",
            "quantity": None
        },

        {
            "component": "Flush Shutter",
            "attribute": "width",
            "type": "formula",
            "formula_used": "frame_vertical_length-frame_vertical_thickness+offset-cut",
            "quantity": None
        }

    ])

    show_component_calculator(sample_rules)
