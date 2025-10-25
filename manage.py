"""
ProManage Streamlit (Advanced) single-file app (app.py)

Advanced Features:
- User Authentication (Login/Register) with hashed passwords
- Multi-Page Navigation (Dashboard, Project, My Tasks)
- Task Management (Kanban board: To Do, In Progress, Done)
- Task creation with assignees, priority, and due dates
- Team Management (Add users to projects)
- Collaboration (Project-level commenting / activity feed)
- Dashboard (My open tasks, stats)
- Retains all original file versioning features under a 'Files' tab
- Ability to upload single files to existing folders

Requirements:
- pip install streamlit pymongo cloudinary python-dotenv tqdm passlib[bcrypt] streamlit-option-menu
- Create a .env with MONGO_URI, MONGO_DB (optional), CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET

Run:
streamlit run app.py
"""

import streamlit as st
from pymongo import MongoClient
import cloudinary
import cloudinary.uploader
from dotenv import load_dotenv
import os, tempfile, shutil, zipfile, datetime, hashlib, requests
from pathlib import Path
from bson import ObjectId
from bson.errors import InvalidId
from tqdm import tqdm
from passlib.context import CryptContext
from streamlit_option_menu import option_menu

# ----------------- Configuration -----------------
load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB = os.getenv("MONGO_DB", "promanage_db_advanced")
CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME")
CLOUD_KEY = os.getenv("CLOUDINARY_API_KEY")
CLOUD_SECRET = os.getenv("CLOUDINARY_API_SECRET")

# --- New Collections ---
# projects_col
# nodes_col
# versions_col
# users_col
# tasks_col
# comments_col

# --- Password Hashing ---
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ----------------- Initialize services -----------------
@st.cache_resource
def init_services():
    """Initialize MongoDB and Cloudinary connections."""
    if not MONGO_URI or not CLOUD_NAME or not CLOUD_KEY or not CLOUD_SECRET:
        st.error("Missing required env vars. Please set all MONGO_URI and CLOUDINARY vars in .env")
        st.stop()
        
    client = MongoClient(MONGO_URI)
    db = client[MONGO_DB]
    
    cloudinary.config(
        cloud_name=CLOUD_NAME,
        api_key=CLOUD_KEY,
        api_secret=CLOUD_SECRET,
        secure=True
    )
    
    # Ensure indexes for faster queries
    try:
        db["users"].create_index("username", unique=True)
        db["nodes"].create_index([("projectId", 1), ("parent", 1)])
        db["nodes"].create_index([("projectId", 1), ("path", 1)])
        db["tasks"].create_index([("projectId", 1), ("status", 1)])
        db["tasks"].create_index([("assigneeId", 1), ("status", 1)])
        db["comments"].create_index([("resourceId", 1), ("createdAt", -1)])
    except Exception as e:
        st.warning(f"Could not create DB indexes: {e}")

    return db

db = init_services()

# --- Collection Variables ---
projects_col = db["projects"]
nodes_col = db["nodes"]
versions_col = db["versions"]
users_col = db["users"]
tasks_col = db["tasks"]
comments_col = db["comments"]


# ----------------- Authentication Functions -----------------

def get_password_hash(password):
    return pwd_context.hash(password)

def verify_password(plain_password, hashed_password):
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception:
        return False

def render_login_page():
    """Show login and registration forms."""
    st.title("Welcome to ProManage 🚀")
    
    login_tab, reg_tab = st.tabs(["Login", "Register"])

    with login_tab:
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Login")
            
            if submitted:
                user = users_col.find_one({"username": username})
                if user and verify_password(password, user["hashed_password"]):
                    st.session_state.user = user  # Log in
                    st.rerun()
                else:
                    st.error("Invalid username or password")

    with reg_tab:
        with st.form("register_form"):
            username = st.text_input("Choose Username")
            password = st.text_input("Choose Password", type="password")
            confirm_password = st.text_input("Confirm Password", type="password")
            submitted = st.form_submit_button("Register")
            
            if submitted:
                if not username or not password:
                    st.error("All fields are required")
                elif password != confirm_password:
                    st.error("Passwords do not match")
                elif users_col.find_one({"username": username}):
                    st.error("Username already exists")
                else:
                    hashed_password = get_password_hash(password)
                    user_doc = {
                        "username": username,
                        "hashed_password": hashed_password,
                        "createdAt": datetime.datetime.utcnow()
                    }
                    res = users_col.insert_one(user_doc)
                    user_doc["_id"] = res.inserted_id
                    st.session_state.user = user_doc  # Log in
                    st.success("Registration successful! You are now logged in.")
                    st.rerun()

# ----------------- Database Helper Functions (Cached) -----------------

@st.cache_data(ttl=60)
def get_user_by_id(user_id):
    try:
        return users_col.find_one({"_id": ObjectId(user_id)})
    except InvalidId:
        return None

@st.cache_data(ttl=60)
def get_all_users():
    """Returns a list of all users, minimal info."""
    return list(users_col.find({}, {"_id": 1, "username": 1}))

@st.cache_data(ttl=30)
def get_projects_for_user(user_id):
    """Get projects where user is a member."""
    return list(projects_col.find({"members": user_id}).sort("createdAt", -1))

@st.cache_data(ttl=10)
def get_project_by_id(project_id):
    try:
        return projects_col.find_one({"_id": ObjectId(project_id)})
    except InvalidId:
        return None

@st.cache_data(ttl=10)
def get_tasks_for_project(project_id):
    return list(tasks_col.find({"projectId": ObjectId(project_id)}).sort("createdAt", -1))

@st.cache_data(ttl=10)
def get_tasks_for_user(user_id):
    return list(tasks_col.find({"assigneeId": user_id}).sort("dueDate", 1))

@st.cache_data(ttl=10)
def get_comments_for_resource(resource_id):
    """Get comments for a project or task."""
    return list(comments_col.find({"resourceId": ObjectId(resource_id)}).sort("createdAt", -1))

# ----------------- Utility functions (Original) -----------------

def compute_checksum(path, algo="sha256"):
    h = hashlib.new(algo)
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return f"{algo}:{h.hexdigest()}"


def copy_project_excluding(src_dir, exclude_dirs=("node_modules", ".git", "venv", ".venv")):
    src = Path(src_dir)
    if not src.exists():
        raise FileNotFoundError(f"Source {src_dir} does not exist")
    tmp_root = Path(tempfile.mkdtemp(prefix="projcopy_"))
    dst = tmp_root / src.name
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(*exclude_dirs))
    return dst


def zip_directory(dir_path, out_zip_path=None):
    dir_path = Path(dir_path)
    if out_zip_path is None:
        out_zip_path = dir_path.with_suffix('.zip')
    with zipfile.ZipFile(out_zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(dir_path):
            for f in files:
                full = Path(root) / f
                rel = full.relative_to(dir_path.parent)
                zf.write(full, arcname=str(rel))
    return Path(out_zip_path)


# ------------- Mongo helper: folder nodes (Original) --------------

def get_or_create_root_folder(project_id, user_id):
    node = nodes_col.find_one({"projectId": ObjectId(project_id), "parent": None, "type": "folder"})
    if node:
        return node
    now = datetime.datetime.utcnow()
    doc = {
        "projectId": ObjectId(project_id),
        "type": "folder",
        "name": "/",
        "parent": None,
        "path": "/",
        "createdBy": user_id,
        "createdAt": now,
        "updatedAt": now
    }
    res = nodes_col.insert_one(doc)
    doc["_id"] = res.inserted_id
    return doc


def get_or_create_folder_node(project_id, rel_dir: Path, user_id):
    # rel_dir: Path relative to project root (could be Path('.'))
    if str(rel_dir) == '.':
        return get_or_create_root_folder(project_id, user_id)
    
    parent = get_or_create_root_folder(project_id, user_id)["_id"]
    
    current_path = Path("/")
    parts = rel_dir.parts
    
    for part in parts:
        current_path = current_path / part
        q = {"projectId": ObjectId(project_id), "type": "folder", "name": part, "parent": parent}
        node = nodes_col.find_one(q)
        if not node:
            now = datetime.datetime.utcnow()
            node_doc = {
                "projectId": ObjectId(project_id),
                "type": "folder",
                "name": part,
                "parent": parent,
                "path": str(current_path).replace("\\", "/"),
                "createdBy": user_id,
                "createdAt": now,
                "updatedAt": now
            }
            res = nodes_col.insert_one(node_doc)
            node_doc["_id"] = res.inserted_id
            node = node_doc
        parent = node["_id"]
    return node


# ------------- Upload functions (Original + Modified) ---------------------

def upload_zip_to_cloudinary(zip_path: Path, project_id: str, version_label: str):
    public_id = f"projects/{project_id}/{version_label}/{zip_path.stem}"
    res = cloudinary.uploader.upload(str(zip_path), resource_type="raw", public_id=public_id, overwrite=True)
    return res


def upload_file_to_cloudinary(local_path: Path, project_id: str, version_label: str, rel_dir: Path):
    rel_str = str((Path(rel_dir) / local_path.name)).replace('\\', '/').lstrip('/')
    public_id = f"projects/{project_id}/{version_label}/{rel_str}"
    res = cloudinary.uploader.upload(str(local_path), resource_type="raw", public_id=public_id, overwrite=True)
    return res

# --- New Function: Upload a single file from Streamlit's uploader ---
def upload_single_file(project_id, user_id, parent_folder_node, uploaded_file):
    """
    Handles uploading a single file to Cloudinary and creating its node doc.
    """
    version_label = f"file-upload-{datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    parent_path = Path(parent_folder_node.get("path", "/"))
    
    # Save to temp file to upload and get checksum
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp.write(uploaded_file.getvalue())
        tmp_path = Path(tmp.name)

    try:
        # Upload to Cloudinary
        res = upload_file_to_cloudinary(tmp_path, project_id, version_label, parent_path)
        checksum = compute_checksum(tmp_path)
        now = datetime.datetime.utcnow()
        
        file_path = str(parent_path / uploaded_file.name).replace("\\", "/")
        if file_path == "/.": file_path = f"/{uploaded_file.name}"

        # Set any previous 'latest' for this path to false
        nodes_col.update_many(
            {"projectId": ObjectId(project_id), "path": file_path, "isLatest": True},
            {"$set": {"isLatest": False}}
        )

        # Create new node doc
        node_doc = {
            "projectId": ObjectId(project_id),
            "type": "file",
            "name": uploaded_file.name,
            "parent": parent_folder_node["_id"],
            "path": file_path,
            "createdBy": user_id,
            "createdAt": now,
            "updatedAt": now,
            "fileMeta": {
                "cloudinary_public_id": res.get("public_id"),
                "cloudinary_url": res.get("secure_url"),
                "size": res.get("bytes"),
                "mime": res.get("resource_type"),
                "versionTag": version_label,
                "timestamp": now,
                "checksum": checksum,
                "original_filename": uploaded_file.name
            },
            "isLatest": True
        }
        nodes_col.insert_one(node_doc)
        return True
    
    except Exception as e:
        st.error(f"Failed to upload {uploaded_file.name}: {e}")
        return False
    
    finally:
        os.unlink(tmp_path) # Clean up temp file


# ------------- Core flow: create version from folder/zip (Original) --------------

def create_version_from_local_folder(project_id, local_folder_path, version_label, user_id, notes=""):
    # 1. copy excluding node_modules
    copied = copy_project_excluding(local_folder_path)
    # 2. zip it
    zip_path = zip_directory(copied)
    # 3. upload zip
    zip_res = upload_zip_to_cloudinary(zip_path, project_id, version_label)
    checksum = compute_checksum(zip_path)
    now = datetime.datetime.utcnow()
    version_doc = {
        "projectId": ObjectId(project_id),
        "version": version_label,
        "label": version_label,
        "notes": notes,
        "createdBy": user_id,
        "createdAt": now,
        "zipCloudinary": {
            "public_id": zip_res.get("public_id"),
            "url": zip_res.get("secure_url"),
            "bytes": zip_res.get("bytes"),
            "checksum": checksum
        }
    }
    versions_col.insert_one(version_doc)

    # 4. Walk files and upload individual files; populate nodes collection
    root = copied
    uploaded_count = 0
    
    # Set all existing files for this project to not latest
    nodes_col.update_many(
        {"projectId": ObjectId(project_id), "type": "file"},
        {"$set": {"isLatest": False}}
    )

    for root_dir, dirs, files in os.walk(root):
        rel_dir = Path(root_dir).relative_to(root)
        folder_node = get_or_create_folder_node(project_id, rel_dir, user_id)
        
        for f in files:
            full = Path(root_dir) / f
            
            try:
                res = upload_file_to_cloudinary(full, project_id, version_label, rel_dir)
            except Exception as e:
                st.warning(f"Upload failed for {full}: {e}")
                continue
                
            checksum = compute_checksum(full)
            now = datetime.datetime.utcnow()
            
            file_path = str(Path("/") / rel_dir / f).replace("\\", "/")
            if file_path == "/.": file_path = f"/{f}"

            node_doc = {
                "projectId": ObjectId(project_id),
                "type": "file",
                "name": f,
                "parent": folder_node["_id"],
                "path": file_path,
                "createdBy": user_id,
                "createdAt": now,
                "updatedAt": now,
                "fileMeta": {
                    "cloudinary_public_id": res.get("public_id"),
                    "cloudinary_url": res.get("secure_url"),
                    "size": res.get("bytes"),
                    "mime": res.get("resource_type"),
                    "versionTag": version_label,
                    "timestamp": now,
                    "checksum": checksum,
                    "original_filename": f
                },
                "isLatest": True
            }
            # Use update_one with upsert=True to create new or update existing file path
            nodes_col.update_one(
                {"projectId": ObjectId(project_id), "path": file_path},
                {"$set": node_doc},
                upsert=True
            )
            uploaded_count += 1

    # cleanup
    try:
        shutil.rmtree(copied.parent)
    except Exception:
        pass

    return {"version": version_doc, "files_uploaded": uploaded_count}


def create_version_from_zip_upload(project_id, uploaded_zip, version_label, user_id, notes=""):
    # uploaded_zip is a tempfile-like object (UploadedFile)
    tmp = tempfile.mkdtemp(prefix="uploaded_zip_")
    zip_path = Path(tmp) / uploaded_zip.name
    with open(zip_path, "wb") as f:
        f.write(uploaded_zip.getvalue())
    # extract to folder
    extract_dir = Path(tmp) / (Path(uploaded_zip.name).stem)
    with zipfile.ZipFile(zip_path, 'r') as zf:
        zf.extractall(extract_dir)
    # reuse folder flow
    result = create_version_from_local_folder(project_id, extract_dir, version_label, user_id, notes)
    # remove tmp
    try:
        shutil.rmtree(tmp)
    except Exception:
        pass
    return result

# ----------------- UI: Project Page > Files Tab (Refactored) -----------------

def render_files_tab(project_id, user_id):
    """Renders the UI for the 'Files' tab, including versioning and file explorer."""
    
    st.subheader("Create a new version")
    st.info("Creating a new version will upload all project files and set them as the 'latest'.")
    
    col1, col2 = st.columns(2)
    with col1:
        with st.expander("**Option A — Upload a ZIP (recommended)**"):
            with st.form("zip_upload_form"):
                uploaded_zip = st.file_uploader("Upload project ZIP", type=["zip"])
                vz = st.text_input("Version label (e.g. v1.0)")
                notes = st.text_area("Notes for this version")
                zip_submit = st.form_submit_button("Create version from ZIP")
                
                if zip_submit:
                    if not uploaded_zip or not vz:
                        st.error("Upload a ZIP and provide a version label")
                    else:
                        with st.spinner("Processing ZIP — extracting, uploading files, saving metadata..."):
                            res = create_version_from_zip_upload(project_id, uploaded_zip, vz, user_id, notes=notes)
                            st.success(f"Version created: {vz}. Files uploaded: {res['files_uploaded']}")
                            st.cache_data.clear() # Clear caches to refresh file view
                            st.rerun()

    with col2:
        with st.expander("**Option B — Use a server-side folder path**"):
            with st.form("folder_upload_form"):
                local_path = st.text_input("Enter absolute server folder path")
                vz2 = st.text_input("Version label (server folder)")
                notes2 = st.text_area("Notes for folder version")
                folder_submit = st.form_submit_button("Create version from folder path")
                
                if folder_submit:
                    if not local_path or not vz2:
                        st.error("Provide path and version label")
                    else:
                        try:
                            with st.spinner("Copying folder, zipping and uploading..."):
                                result = create_version_from_local_folder(project_id, local_path, vz2, user_id, notes=notes2)
                                st.success(f"Version {vz2} created. Files uploaded: {result['files_uploaded']}")
                                st.cache_data.clear() # Clear caches
                                st.rerun()
                        except Exception as e:
                            st.error(f"Error: {e}")

    st.markdown("---")
    
    # list versions
    st.subheader("Project Versions (Full Snapshots)")
    versions = list(versions_col.find({"projectId": ObjectId(project_id)}).sort("createdAt", -1))
    if versions:
        with st.expander("Show project version history"):
            for v in versions:
                cols = st.columns([6, 2, 2])
                cols[0].markdown(f"**{v.get('version')}** — *{v.get('notes','')}*")
                zip_info = v.get('zipCloudinary', {})
                if zip_info.get('url'):
                    cols[1].link_button("Download ZIP", zip_info.get('url'))
                cols[2].write(v.get('createdAt').strftime('%Y-%m-%d %H:%M'))
    else:
        st.write("No full project versions yet.")

    st.markdown("---")
    
    # File browser
    st.subheader("File Explorer (Latest Files)")
    st.write("This shows the most recent version of each file.")
    
    @st.cache_data(ttl=10)
    def get_file_tree(project_id, parent_id):
        return list(nodes_col.find(
            {"projectId": ObjectId(project_id), "parent": parent_id, "$or": [{"type": "folder"}, {"isLatest": True}]}
        ).sort([('type', -1), ('name', 1)])) # Folders first

    def render_folder(parent_node):
        children = get_file_tree(project_id, parent_node["_id"])
        
        # --- New: Single File Upload ---
        with st.popover("Upload File(s) Here"):
            with st.form(f"upload-form-{parent_node['_id']}"):
                files_to_upload = st.file_uploader("Upload new file(s)", accept_multiple_files=True, key=f"uploader_{parent_node['_id']}")
                submitted = st.form_submit_button("Upload")
                
                if submitted and files_to_upload:
                    with st.spinner("Uploading files..."):
                        count = 0
                        for f in files_to_upload:
                            if upload_single_file(project_id, user_id, parent_node, f):
                                count += 1
                        st.success(f"Uploaded {count} file(s).")
                        st.cache_data.clear()
                        st.rerun()

        for node in children:
            if node["type"] == "folder":
                with st.expander(f"📁 {node['name']}", expanded=False):
                    render_folder(node) # Recursive call
            else:
                # File node
                cols = st.columns([5, 1, 1, 1])
                cols[0].write(f"📄 {node['name']}")
                
                if cols[1].button("Preview", key=f"pv_{str(node['_id'])}", use_container_width=True):
                    show_file_preview(node)
                    
                if cols[2].button("History", key=f"vs_{str(node['_id'])}", use_container_width=True):
                    show_file_versions(node)
                    
                cols[3].link_button("DL", node['fileMeta']['cloudinary_url'], use_container_width=True, help="Download")

    @st.dialog("File Preview")
    def show_file_preview(node):
        url = node.get('fileMeta', {}).get('cloudinary_url')
        if not url:
            st.warning('No URL to preview')
            return
        
        st.write(f"**Preview: {node.get('name', 'file')}**")
        st.link_button("Download File", url)
        
        ext = Path(node.get('name', '')).suffix.lower()
        text_exts = {'.py', '.js', '.java', '.txt', '.md', '.json', '.html', '.css', '.c', '.cpp', '.go', '.rs', '.toml', '.yaml', '.yml'}
        
        if ext in text_exts:
            try:
                r = requests.get(url)
                if r.status_code == 200:
                    st.code(r.text, language=ext.lstrip('.'))
                else:
                    st.write(f"Unable to fetch file (status {r.status_code})")
            except Exception as e:
                st.write(f"Preview error: {e}")
        else:
            st.write(f"Preview not available for {ext} files. Please download.")

    @st.dialog("File Version History")
    def show_file_versions(node):
        path = node.get('path')
        if not path:
            st.warning('No path available')
            return

        st.write(f"**History for: {node.get('name')}**")
        
        files = list(nodes_col.find(
            {"projectId": ObjectId(project_id), "path": path}
        ).sort([('fileMeta.timestamp', -1)]))
        
        if not files:
            st.write('No historical versions')
            return
        
        for f in files:
            meta = f.get('fileMeta', {})
            is_latest = f.get('isLatest', False)
            label = " (Latest)" if is_latest else ""
            
            st.markdown(f"**Version: {meta.get('versionTag')}{label}**")
            st.write(f"Date: {meta.get('timestamp').strftime('%Y-%m-%d %H:%M')}")
            st.link_button(f"Download this version", meta.get('cloudinary_url'))
            st.markdown("---")

    # Start rendering file tree from root
    root_node = get_or_create_root_folder(project_id, user_id)
    if root_node:
        render_folder(root_node)
    else:
        st.write("Project has no files yet.")


# ----------------- UI: Project Page > Tasks Tab (New) -----------------

def render_tasks_tab(project_id, user_id, all_users):
    """Renders the Kanban board for tasks."""
    st.subheader("Task Board")
    
    user_map = {str(u["_id"]): u["username"] for u in all_users}
    user_options = [(u["username"], str(u["_id"])) for u in all_users]

    # --- New Task Button ---
    with st.popover("New Task"):
        with st.form("new_task_form"):
            st.write("Create a new task")
            title = st.text_input("Task Title")
            description = st.text_area("Description")
            status = st.selectbox("Status", ["To Do", "In Progress", "Done"], index=0)
            priority = st.selectbox("Priority", ["Low", "Medium", "High"], index=1)
            assignee_id = st.selectbox("Assign To", options=user_options, format_func=lambda x: x[0])
            due_date = st.date_input("Due Date", value=None)
            
            submitted = st.form_submit_button("Create Task")
            if submitted:
                if not title:
                    st.error("Title is required")
                else:
                    task_doc = {
                        "projectId": ObjectId(project_id),
                        "title": title,
                        "description": description,
                        "status": status,
                        "priority": priority,
                        "assigneeId": ObjectId(assignee_id[1]) if assignee_id else None,
                        "dueDate": datetime.datetime.combine(due_date, datetime.time.min) if due_date else None,
                        "createdBy": user_id,
                        "createdAt": datetime.datetime.utcnow(),
                        "updatedAt": datetime.datetime.utcnow()
                    }
                    tasks_col.insert_one(task_doc)
                    st.success("Task created!")
                    st.cache_data.clear() # Clear cache to show new task
                    st.rerun()

    # --- Kanban Columns ---
    tasks = get_tasks_for_project(project_id)
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.header("To Do")
        todo_tasks = [t for t in tasks if t["status"] == "To Do"]
        for task in todo_tasks:
            render_task_card(task, user_map)
            
    with col2:
        st.header("In Progress")
        inprogress_tasks = [t for t in tasks if t["status"] == "In Progress"]
        for task in inprogress_tasks:
            render_task_card(task, user_map)
            
    with col3:
        st.header("Done")
        done_tasks = [t for t in tasks if t["status"] == "Done"]
        for task in done_tasks:
            render_task_card(task, user_map)

def render_task_card(task, user_map):
    """Displays a single task card."""
    
    def handle_status_change(task_id, new_status):
        tasks_col.update_one(
            {"_id": task_id},
            {"$set": {"status": new_status, "updatedAt": datetime.datetime.utcnow()}}
        )
        st.cache_data.clear()
    
    task_id = task["_id"]
    with st.container(border=True):
        st.markdown(f"**{task['title']}**")
        
        cols = st.columns([3, 2])
        
        # Priority
        priority_colors = {"Low": "blue", "Medium": "orange", "High": "red"}
        cols[0].markdown(f":{priority_colors[task['priority']]}[{task['priority']} Priority]")
        
        # Due Date
        if task.get("dueDate"):
            due = task['dueDate'].strftime('%Y-%m-%d')
            if task['dueDate'] < datetime.datetime.now() and task['status'] != 'Done':
                cols[1].markdown(f"🗓️ **:red[{due}]**")
            else:
                cols[1].markdown(f"🗓️ {due}")

        # Assignee
        assignee_name = "Unassigned"
        if task.get("assigneeId") and str(task["assigneeId"]) in user_map:
            assignee_name = user_map[str(task["assigneeId"])]
        st.write(f"🧑‍💻 {assignee_name}")
        
        # Status Changer
        status_options = ["To Do", "In Progress", "Done"]
        current_index = status_options.index(task["status"])
        st.selectbox(
            "Change Status", 
            options=status_options, 
            index=current_index, 
            key=f"status_{task_id}",
            label_visibility="collapsed",
            on_change=lambda: handle_status_change(task_id, st.session_state[f"status_{task_id}"])
        )

        with st.expander("Details..."):
            st.write(task.get("description", "No description."))
            st.caption(f"Created: {task['createdAt'].strftime('%Y-%m-%d')}")


# ----------------- UI: Project Page > Overview Tab (New) -----------------

def render_overview_tab(project_id, user_id, all_users):
    """Renders the project overview with stats and activity feed."""
    
    project = get_project_by_id(project_id)
    if not project:
        st.error("Project not found.")
        return
        
    st.write(project.get("description", "No description for this project."))
    st.markdown("---")
    
    # --- Task Stats ---
    st.subheader("Task Status")
    tasks = get_tasks_for_project(project_id)
    if tasks:
        status_counts = {"To Do": 0, "In Progress": 0, "Done": 0}
        for t in tasks:
            status_counts[t["status"]] += 1
        
        chart_data = {"Status": status_counts.keys(), "Count": status_counts.values()}
        st.bar_chart(chart_data, x="Status", y="Count")
    else:
        st.write("No tasks yet for this project.")
        
    st.markdown("---")

    # --- Activity Feed (Comments) ---
    st.subheader("Activity Feed")
    
    with st.popover("Post a Comment"):
        with st.form("new_comment_form"):
            comment_text = st.text_area("Add a comment or update...")
            submitted = st.form_submit_button("Post")
            
            if submitted and comment_text:
                comment_doc = {
                    "resourceId": ObjectId(project_id),
                    "resourceType": "project",
                    "userId": user_id,
                    "text": comment_text,
                    "createdAt": datetime.datetime.utcnow()
                }
                comments_col.insert_one(comment_doc)
                st.success("Comment posted!")
                st.cache_data.clear()
                st.rerun()

    comments = get_comments_for_resource(project_id)
    user_cache = {str(u["_id"]): u["username"] for u in all_users}
    
    if not comments:
        st.write("No activity yet.")
    else:
        for c in comments:
            username = user_cache.get(str(c["userId"]), "Unknown User")
            with st.container(border=True):
                st.markdown(f"**{username}** · *{c['createdAt'].strftime('%Y-%m-%d %H:%M')}*")
                st.write(c["text"])


# ----------------- UI: Project Page > Team Tab (New) -----------------

def render_team_tab(project_doc, all_users):
    """Renders the team management tab."""
    st.subheader("Team Members")
    
    project_id = project_doc["_id"]
    owner_id = project_doc.get("ownerId")
    member_ids = project_doc.get("members", [])
    
    user_map = {str(u["_id"]): u["username"] for u in all_users}
    
    for user_id in member_ids:
        username = user_map.get(str(user_id), f"Unknown ID: {user_id}")
        label = " (Owner)" if user_id == owner_id else ""
        st.write(f"🧑‍💻 {username}{label}")

    st.markdown("---")
    
    # --- Add Members ---
    st.subheader("Add Members")
    non_member_options = [
        (u["username"], str(u["_id"])) for u in all_users 
        if ObjectId(u["_id"]) not in member_ids
    ]
    
    if not non_member_options:
        st.write("All users are already in this project.")
    else:
        with st.form("add_member_form"):
            users_to_add = st.multiselect(
                "Select users to add",
                options=non_member_options,
                format_func=lambda x: x[0]
            )
            submitted = st.form_submit_button("Add to Project")
            
            if submitted and users_to_add:
                new_member_ids = [ObjectId(uid[1]) for uid in users_to_add]
                projects_col.update_one(
                    {"_id": project_id},
                    {"$push": {"members": {"$each": new_member_ids}}}
                )
                st.success(f"Added {len(new_member_ids)} member(s).")
                st.cache_data.clear()
                st.rerun()

    st.markdown("---")
    
    # --- Danger Zone ---
    if owner_id == st.session_state.user["_id"]:
        st.subheader("Danger Zone")
        if st.button("Delete Project", type="primary"):
            st.session_state.delete_confirm = True

        if "delete_confirm" in st.session_state and st.session_state.delete_confirm:
            st.warning(f"This will delete the project, all tasks, and all files. This cannot be undone.")
            if st.button("I understand, delete this project"):
                # In a real app, you'd delete from Cloudinary too (complex).
                # For this demo, we just delete from DB.
                nodes_col.delete_many({"projectId": project_id})
                versions_col.delete_many({"projectId": project_id})
                tasks_col.delete_many({"projectId": project_id})
                comments_col.delete_many({"projectId": project_id})
                projects_col.delete_one({"_id": project_id})
                
                del st.session_state.delete_confirm
                del st.session_state.selected_project_id
                st.success("Project deleted.")
                st.cache_data.clear()
                st.rerun()

# ----------------- UI: Dashboard Page (New) -----------------

def render_dashboard(user_id):
    """Renders the main dashboard."""
    st.title(f"Welcome, {st.session_state.user['username']}!")
    
    st.subheader("My Open Tasks")
    my_tasks = get_tasks_for_user(user_id)
    open_tasks = [t for t in my_tasks if t["status"] != "Done"]
    
    if not open_tasks:
        st.write("You have no open tasks. 🎉")
    else:
        projects = {str(p["_id"]): p["name"] for p in get_projects_for_user(user_id)}
        for task in open_tasks:
            proj_name = projects.get(str(task["projectId"]), "Unknown Project")
            with st.container(border=True):
                st.markdown(f"**{task['title']}** (Project: *{proj_name}*)")
                cols = st.columns(2)
                cols[0].write(f"Status: {task['status']}")
                if task.get("dueDate"):
                    due = task['dueDate'].strftime('%Y-%m-%d')
                    if task['dueDate'] < datetime.datetime.now():
                        cols[1].markdown(f"Due: **:red[{due}]**")
                    else:
                        cols[1].markdown(f"Due: {due}")
    
    st.markdown("---")
    st.subheader("Recent Activity")
    st.write("(Coming soon: A feed of all project updates)")


# ----------------- UI: My Tasks Page (New) -----------------

def render_my_tasks(user_id):
    """Renders a dedicated page for all of the user's tasks."""
    st.title("My Tasks")
    
    my_tasks = get_tasks_for_user(user_id)
    if not my_tasks:
        st.write("You have no tasks assigned to you.")
        st.stop()
        
    projects = {str(p["_id"]): p for p in get_projects_for_user(user_id)}
    
    # Group tasks by project
    tasks_by_project = {}
    for task in my_tasks:
        proj_id = str(task["projectId"])
        if proj_id not in tasks_by_project:
            tasks_by_project[proj_id] = []
        tasks_by_project[proj_id].append(task)
        
    for proj_id, tasks in tasks_by_project.items():
        proj_name = projects.get(proj_id, {}).get("name", "Unknown Project")
        st.subheader(f"Project: {proj_name}")
        
        for task in sorted(tasks, key=lambda x: x.get('dueDate') or datetime.datetime.max):
            cols = st.columns([4, 1, 1])
            cols[0].markdown(f"**{task['title']}**")
            
            priority_colors = {"Low": "blue", "Medium": "orange", "High": "red"}
            cols[1].markdown(f":{priority_colors[task['priority']]}[{task['priority']}]")

            if task.get("dueDate"):
                due = task['dueDate'].strftime('%Y-%m-%d')
                if task['dueDate'] < datetime.datetime.now() and task['status'] != 'Done':
                    cols[2].markdown(f"🗓️ **:red[{due}]**")
                else:
                    cols[2].markdown(f"🗓️ {due}")
            
            with st.expander("Details", expanded=False):
                st.write(task.get("description", "No description."))
                st.write(f"Status: **{task['status']}**")


# ----------------- Main App Logic -----------------

def main():
    st.set_page_config(page_title="ProManage", layout="wide")

    # --- Authentication Gate ---
    if "user" not in st.session_state:
        render_login_page()
        st.stop()

    # --- Main App UI ---
    user_id = st.session_state.user["_id"]
    
    with st.sidebar:
        st.markdown(f"Welcome, **{st.session_state.user['username']}**")
        
        if st.button("Logout"):
            del st.session_state.user
            st.rerun()
            
        st.markdown("---")

        # --- Page Navigation ---
        page = option_menu(
            None, ["Dashboard", "Project", "My Tasks"],
            icons=["kanban", "archive", "list-task"],
            menu_icon="cast", default_index=0
        )
        
        st.markdown("---")
        
        # --- Project Selector ---
        st.header("Projects")
        with st.form("create_proj_form", clear_on_submit=True):
            proj_name = st.text_input("New Project Name")
            proj_desc = st.text_area("Description")
            create_btn = st.form_submit_button("Create Project")
            
            if create_btn and proj_name:
                now = datetime.datetime.utcnow()
                proj_doc = {
                    "name": proj_name, 
                    "description": proj_desc, 
                    "createdAt": now,
                    "ownerId": user_id,
                    "members": [user_id] # Creator is the first member
                }
                res = projects_col.insert_one(proj_doc)
                st.success(f"Created project {proj_name}")
                st.cache_data.clear() # Refresh project list

        projects = get_projects_for_user(user_id)
        if projects:
            proj_map = {str(p["_id"]): p for p in projects}
            proj_options = [(p['name'], str(p['_id'])) for p in projects]
            
            # Find index of last selected project
            idx = 0
            if "selected_project_id" in st.session_state:
                try:
                    idx = [pid for name, pid in proj_options].index(st.session_state.selected_project_id)
                except ValueError:
                    pass # Project not in list (e.g., deleted)
            
            selected_id = st.selectbox(
                "Select a project", 
                options=proj_options, 
                format_func=lambda x: x[0],
                index=idx,
                key="project_selector"
            )
            
            if selected_id:
                st.session_state.selected_project_id = selected_id[1]
        
        else:
            st.info("No projects yet. Create one!")

    # --- Page Rendering ---
    if page == "Dashboard":
        render_dashboard(user_id)
        
    elif page == "My Tasks":
        render_my_tasks(user_id)
        
    elif page == "Project":
        if "selected_project_id" not in st.session_state:
            st.info("Please select a project from the sidebar to view details.")
            st.stop()
        
        project = get_project_by_id(st.session_state.selected_project_id)
        if not project:
            st.error("Project not found or you do not have access.")
            del st.session_state.selected_project_id
            st.stop()

        st.title(f"Project: {project['name']}")
        
        all_users = get_all_users() # Get user list once for all tabs
        
        overview_tab, tasks_tab, files_tab, team_tab = st.tabs(
            ["📊 Overview", "📋 Tasks", "🗂️ Files & Versions", "🧑‍🤝‍🧑 Team & Settings"]
        )
        
        with overview_tab:
            render_overview_tab(project["_id"], user_id, all_users)
            
        with tasks_tab:
            render_tasks_tab(project["_id"], user_id, all_users)

        with files_tab:
            render_files_tab(str(project["_id"]), user_id)
            
        with team_tab:
            render_team_tab(project, all_users)

if __name__ == "__main__":
    main()