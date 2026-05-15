import os
import psycopg2
import streamlit as st


# =========================================================
# PAGE CONFIG
# =========================================================
st.set_page_config(
    page_title="OperaFlow Component App",
    layout="wide",
    initial_sidebar_state="expanded"
)


# =========================================================
# SESSION DEFAULTS
# =========================================================
defaults = {
    "logged_in": False,
    "role": None,
    "page": "Component Calculator"
}

for key, value in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value


# =========================================================
# LOGIN PAGE
# =========================================================
def login():

    st.title("OperaFlow")
    st.subheader("Component Fabrication & Tracking System")

    username = st.text_input("Username")
    password = st.text_input("Password", type="password")

    if st.button("Sign In"):

        users = {
            "admin": {
                "password": "admin@123",
                "role": "admin"
            },
            "production": {
                "password": "123",
                "role": "production"
            }
        }

        if username in users:

            if users[username]["password"] == password:

                st.session_state.logged_in = True
                st.session_state.role = users[username]["role"]

                st.rerun()

        st.error("Invalid credentials")


# =========================================================
# LOGIN CHECK
# =========================================================
if not st.session_state.logged_in:
    login()
    st.stop()


# =========================================================
# DATABASE CONNECTION
# =========================================================
def create_connection():

    return psycopg2.connect(
        host=st.secrets["DB_HOST"],
        port=st.secrets["DB_PORT"],
        database=st.secrets["DB_NAME"],
        user=st.secrets["DB_USER"],
        password=st.secrets["DB_PASSWORD"]
    )


conn = create_connection()
cur = conn.cursor()


# =========================================================
# SIDEBAR
# =========================================================
with st.sidebar:

    st.title("OperaFlow")

    st.markdown(
        f"Logged in as: {st.session_state.role.upper()}"
    )

    st.markdown("---")

    pages = [
        "Component Calculator",
        "Tracking",
        "Upload Data"
    ]

    selected_page = st.radio(
        "Navigation",
        pages
    )

    st.session_state.page = selected_page

    st.markdown("---")

    if st.button("Logout"):

        st.session_state.logged_in = False
        st.session_state.role = None

        st.rerun()


# =========================================================
# PAGE ROUTER
# =========================================================
try:

    if selected_page == "Component Calculator":

        from component_calculator import show_component_calculator

        show_component_calculator(conn, cur)

    elif selected_page == "Tracking":

        from tracking import show_tracking

        show_tracking(conn, cur)

    elif selected_page == "Upload Data":

        from upload import show_upload

        show_upload(conn, cur)

except Exception as e:

    conn.rollback()

    st.error(f"Error: {e}")

finally:

    cur.close()
    conn.close()
