import requests
import os
from dotenv import load_dotenv
import streamlit as st
import re

load_dotenv()
ASANA_TOKEN = os.getenv("ASANA_TOKEN")
WORKSPACE_ID = "1214051352006115"
PROJECT_ID = "1214024107011760"

headers = {
    "Authorization": f"Bearer {ASANA_TOKEN}",
    "Content-Type": "application/json"
}

FIELD_IDS = {
    "fiber_ran": "1214032515160799",
    "copper_ran": "1214032515160803",
    "runners": "1214032515160807",
    "atl_site": "1214032515160809",
    "brick_patcher": "1214032515160839",
    "fusion_patcher": "1214032515160841",
    "brick_patched": "1214032515160843",
    "fusion_patched": "1214032515160847",
}

ENUM_IDS = {
    "fiber_ran": {
        "Yes": "1214032515160800",
        "No": "1214032515160801",
    },
    "copper_ran": {
        "Yes": "1214032515160804",
        "No": "1214032515160805",
    },
    "brick_patched": {
        "Patched": "1214032515160844",
        "Not Patched": "1214032515160845",
    },
    "fusion_patched": {
        "Patched": "1214032515160848",
        "Not Patched": "1214032515160849",
    },
}


## Find tasks

def find_task_by_name(position):
    response = requests.get(
        f"https://app.asana.com/api/1.0/projects/{PROJECT_ID}/tasks",
        headers=headers,
        params={
            "opt_fields": "gid,name",
            "limit": 100,
        },
    )
    response.raise_for_status()
    tasks = response.json()["data"]

    for task in tasks:
        if task["name"] == position:
            return task["gid"]

    return None


## Fetch users
def fetch_user_map():
    response = requests.get(
        f"https://app.asana.com/api/1.0/workspaces/{WORKSPACE_ID}/users",
        headers=headers,
        params={
            "opt_fields": "gid,name,email"
        },
    )
    response.raise_for_status()
    users = response.json()["data"]

    user_map = {}

    for user in users:
        gid = user["gid"]
        name = user.get("name", "").strip()
        email = user.get("email", "").strip().lower()

        if name:
            user_map[name.lower()] = gid
        if email:
            user_map[email.lower()] = gid
            user_map[email.split("@")[0].lower()] = gid

    return user_map

USER_IDS = fetch_user_map()

def people_values(names):
    if not names:
        return None
    
    gids = []
    for name in names:
        key = name.strip().lower()
        if key not in USER_IDS:
            raise ValueError(f"Unknown user: {name}")
        gids.append(USER_IDS[key])

    return gids

def update_task(position, site, fiber_ran, copper_ran, brick_patched, fusion_patched, runners, brick_patcher, fusion_patcher):
    custom_fields = {
        FIELD_IDS["atl_site"]: SITE_OPTIONS[site],
        FIELD_IDS["fiber_ran"]: ENUM_IDS["fiber_ran"][fiber_ran],
        FIELD_IDS["copper_ran"]: ENUM_IDS["copper_ran"][copper_ran],
    }

    if brick_patched:
        custom_fields[FIELD_IDS["brick_patched"]] = ENUM_IDS["brick_patched"][brick_patched]

    if fusion_patched:
        custom_fields[FIELD_IDS["fusion_patched"]] = ENUM_IDS["fusion_patched"][fusion_patched]
        

    runner_value = people_values(runners)
    brick_patcher_value = people_values(brick_patcher)
    fusion_patcher_value = people_values(fusion_patcher)

    if runner_value is not None:
        custom_fields[FIELD_IDS["runners"]] = runner_value
    if brick_patcher_value is not None:
        custom_fields[FIELD_IDS["brick_patcher"]] = brick_patcher_value
    if fusion_patcher_value is not None:
        custom_fields[FIELD_IDS["fusion_patcher"]] = fusion_patcher_value


    task_gid = find_task_by_name(position)
    if not task_gid:
        raise ValueError(f"Task not found: {position}")

    payload = {
        "data": {
            "custom_fields": custom_fields,
        }
    }

    response = requests.put(
        f"https://app.asana.com/api/1.0/tasks/{task_gid}",
        headers=headers,
        json=payload,
    )
    response.raise_for_status()
    return response.json()


@st.cache_data(ttl=60)
def get_site_options():
    response = requests.get(
        f"https://app.asana.com/api/1.0/projects/{PROJECT_ID}",
        headers=headers,
        params={
            "opt_fields": "custom_field_settings.custom_field.name,custom_field_settings.custom_field.enum_options.name,custom_field_settings.custom_field.enum_options.gid"
        },
    )
    response.raise_for_status()
    project = response.json()["data"]

    site_map = {}
    for setting in project.get("custom_field_settings", []):
        field = setting.get("custom_field", {})
        if field.get("name") == "ATL Site":
            for option in field.get("enum_options", []):
                site_map[option["name"]] = option["gid"]

    return site_map


def get_existing_task_names():
    response = requests.get(
        f"https://app.asana.com/api/1.0/projects/{PROJECT_ID}/tasks",
        headers=headers,
        params={"opt_fields": "name", "limit": 100},
    )
    response.raise_for_status()
    tasks = response.json()["data"]
    return {task["name"] for task in tasks}


## Web App

st.title("Cabling Tracker")
st.text("Note: Settings will apply to all listed positions.")

SITE_OPTIONS = get_site_options()
parsed_positions = []
missing_positions = []

site = st.selectbox("Site", list(SITE_OPTIONS.keys()))
positions_text = st.text_area("Positions (one per line)", placeholder="e.g.\n01-01-002-06\n01-01-003-15")

def parse_positions(site, raw_text):
    positions = []
    for line in raw_text.splitlines():
        cleaned = line.strip()
        if not cleaned:
            continue
        if not re.fullmatch(r"\d{2}-\d{2}-\d{3}-\d{2,3}", cleaned):
            raise ValueError(f"Invalid position format: {cleaned}")
        positions.append(f"{site}.1-{cleaned}")
    return positions

if positions_text.strip():
    try:
        parsed_positions = parse_positions(site, positions_text)
        existing_names = get_existing_task_names()
        missing_positions = [p for p in parsed_positions if p not in existing_names]

        if missing_positions:
            st.error("These positions do not exist in Asana:")
            for pos in missing_positions:
                st.markdown(f"- {pos}")

    except Exception as e:
        st.error(str(e))

fiber_ran = st.selectbox("Fiber Ran", ["Yes", "No"])
copper_ran = st.selectbox("Copper Ran", ["Yes", "No"])
brick_patched = st.selectbox("Brick Patched", ["Patched", "Not Patched", "-"])
fusion_patched = st.selectbox("Fusion Patched", ["Patched", "Not Patched", "-"])

runners_text = st.text_input("Runner(s) (comma separated)")
brick_patcher_text = st.text_input("Brick Patcher(s) (comma separated)")
fusion_patcher_text = st.text_input("Fusion Patcher(s) (comma separated)")


submit_clicked = st.button("Submit", disabled=bool(missing_positions))

if submit_clicked:
    try:
        if brick_patched == "-":
            brick_patched = ""
        if fusion_patched == "-":
            fusion_patched = ""

        runners = [x.strip() for x in runners_text.split(",") if x.strip()]
        brick_patcher = [x.strip() for x in brick_patcher_text.split(",") if x.strip()]
        fusion_patcher = [x.strip() for x in fusion_patcher_text.split(",") if x.strip()]

        positions = parsed_positions

        results = []
        for position in positions:
            update_task(
                position,
                site,
                fiber_ran,
                copper_ran,
                brick_patched,
                fusion_patched,
                runners,
                brick_patcher,
                fusion_patcher
            )
            results.append(position)

        st.balloons()
        st.success(f"Updated {len(results)} tasks")
        with st.expander("View updated positions"):
            for pos in results:
                st.markdown(f"- {pos}")

    except Exception as e:
        st.error(str(e))

# https://app.asana.com/1/1214051352006115/project/1214024107011760/list/1214024107245700