import internetarchive as ia
import json
import os
import zipfile
import shutil
import logging
from datetime import datetime
from mcp.server.fastmcp import FastMCP
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

# Base directory of the script
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, 'eterno.log')

# Create a console for stderr (what the CLI sees)
console = Console(stderr=True)

# Create a second console specifically for the log file to preserve ANSI colors
# force_terminal=True ensures colors are saved even when writing to a file
file_handle = open(LOG_FILE, "a", encoding="utf-8")
file_console = Console(
    file=file_handle, 
    force_terminal=True, 
    width=100
)

def broadcast(renderable):
    """Helper to print rich objects to both CLI and Log File."""
    console.print(renderable)
    file_console.print(renderable)
    file_handle.flush() # Ensure it's written immediately for tail -f

# Configure logging with RichHandler for both destinations
class RichFileHandler(RichHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(console=file_console, *args, **kwargs)

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[
        RichHandler(console=console, rich_tracebacks=True),
        RichFileHandler(rich_tracebacks=True)
    ]
)

logger = logging.getLogger("eterno")

mcp = FastMCP("Eterno")

class LocalJanitor:
    """Safely cleans up localized storage directories."""
    @staticmethod
    def wipe(directory: str):
        if not os.path.exists(directory):
            return
        logger.info(f"Wiping directory: [bold red]{directory}[/bold red]", extra={"markup": True})
        for filename in os.listdir(directory):
            file_path = os.path.join(directory, filename)
            try:
                if os.path.isfile(file_path) or os.path.islink(file_path):
                    os.unlink(file_path)
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
            except Exception as e:
                logger.error(f'Failed to delete {file_path}. Reason: {e}')

@mcp.tool()
def search_internetarchive(query: str, page: int = 1, limit: int = 10) -> str:
    """Search for abandonware/software on Internet Archive. Returns a list of identifiers and pagination info."""
    logger.info(f"🔍 [bold cyan]Searching IA for:[/bold cyan] {query} (Page: {page}, Limit: {limit})", extra={"markup": True})
    
    search_query = f"mediatype:software AND {query}"
    results = ia.search_items(search_query, params={'page': page})
    
    identifiers = []
    table = Table(title=f"Search Results for: {query}")
    table.add_column("Index", style="dim")
    table.add_column("Identifier", style="green")
    
    for i, result in enumerate(results):
        if i >= limit:
            break
        ident = result['identifier']
        identifiers.append(ident)
        table.add_row(str(i+1), ident)
    
    if not identifiers:
        logger.warning(f"❌ No results found for query: {query}")
        return json.dumps({"page": page, "limit": limit, "identifiers": []})
    
    broadcast(table)
    logger.info(f"✅ Found {len(identifiers)} items on page {page}", extra={"markup": True})
    return json.dumps({"page": page, "limit": limit, "identifiers": identifiers})

@mcp.tool()
def get_item_details(identifier: str) -> str:
    """Get metadata and file list for a specific Internet Archive item."""
    logger.info(f"📋 [bold yellow]Fetching details for:[/bold yellow] {identifier}", extra={"markup": True})
    try:
        item = ia.get_item(identifier)
        if not item.exists:
            logger.error(f"❌ Item {identifier} does not exist.")
            return f"Error: Item {identifier} does not exist."
        
        # Display metadata in a panel
        meta_text = Text()
        meta_text.append("Title: ", style="bold")
        meta_text.append(f"{item.metadata.get('title', 'N/A')}\n")
        meta_text.append("Date: ", style="bold")
        meta_text.append(f"{item.metadata.get('date', 'N/A')}\n")
        meta_text.append("Collection: ", style="bold")
        meta_text.append(f"{item.metadata.get('collection', 'N/A')}")
        
        broadcast(Panel(meta_text, title=f"Metadata: {identifier}", border_style="blue"))
        
        # Display files in a table
        file_table = Table(title=f"Files in {identifier}")
        file_table.add_column("File Name", style="cyan")
        file_table.add_column("Size", justify="right", style="magenta")
        
        file_list = []
        for f in item.files:
            file_table.add_row(f["name"], str(f.get("size", "unknown")))
            file_list.append({"name": f["name"], "size": f.get("size")})
            
        broadcast(file_table)
        
        details = {
            "metadata": item.metadata,
            "files": file_list
        }
        return json.dumps(details, indent=2)
    except Exception as e:
        logger.exception(f"💥 Error getting details for {identifier}")
        return f"Error: {str(e)}"

@mcp.tool()
def download_item(identifier: str, content_type: str = "both") -> str:
    """Download files from an Internet Archive item."""
    logger.info(f"📥 [bold green]Downloading {content_type} for:[/bold green] {identifier}", extra={"markup": True})
    download_dir = os.path.join(BASE_DIR, "data/downloads")
    os.makedirs(download_dir, exist_ok=True)
    
    meta_patterns = ["*.txt", "*.nfo", "*.xml", "*.pdf", "*.md", "*_meta.xml", "*_files.xml"]
    soft_patterns = ["*.zip", "*.rar", "*.7z", "*.exe", "*.msi", "*.dmg", "*.pkg", "*.clap", "*.vst3", "*.vst"]
    
    glob_patterns = []
    if content_type == "metadata":
        glob_patterns = meta_patterns
    elif content_type == "software":
        glob_patterns = soft_patterns
    else:
        glob_patterns = [None]
    
    try:
        for pattern in glob_patterns:
            logger.info(f"   - Pattern: [blue]{pattern if pattern else 'All'}[/blue]", extra={"markup": True})
            ia.download(identifier, destdir=download_dir, glob_pattern=pattern, verbose=False, ignore_existing=True)
        
        item_path = os.path.join(download_dir, identifier)
        if not os.path.exists(item_path):
            logger.warning(f"⚠️ No files matching '{content_type}' found.")
            return f"No files matching '{content_type}' were found for {identifier}."
        
        files = os.listdir(item_path)
        logger.info(f"✨ [bold green]Successfully downloaded {len(files)} files.[/bold green]", extra={"markup": True})
        return f"Successfully downloaded/checked {len(files)} files in {item_path}."
    except Exception as e:
        logger.error(f"💥 Download error: {str(e)}")
        return f"Error: {str(e)}"

@mcp.tool()
def inspect_and_read_docs(identifier: str) -> str:
    """Extract any downloaded archives and read documentation files."""
    logger.info(f"🔍 [bold magenta]Inspecting contents:[/bold magenta] {identifier}", extra={"markup": True})
    download_dir = os.path.join(BASE_DIR, "data/downloads")
    extract_dir = os.path.join(BASE_DIR, "data/extracted")
    os.makedirs(extract_dir, exist_ok=True)
    
    item_path = os.path.join(download_dir, identifier)
    if not os.path.exists(item_path):
        return f"Error: No downloaded files found for {identifier}. Call download_item first."
    
    extracted_content = []
    
    for root, _, files in os.walk(item_path):
        for file in files:
            file_path = os.path.join(root, file)
            
            if file.lower().endswith(".zip"):
                logger.info(f"📦 [cyan]Extracting:[/cyan] {file}", extra={"markup": True})
                try:
                    with zipfile.ZipFile(file_path, 'r') as zip_ref:
                        zip_ref.extractall(extract_dir)
                except Exception as e:
                    logger.error(f"Error extracting {file}: {str(e)}")
            
            if file.lower().endswith((".txt", ".nfo", ".md")):
                logger.info(f"📄 [yellow]Reading:[/yellow] {file}", extra={"markup": True})
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read(10000)
                        extracted_content.append(f"--- {file} ---\n{content}")
                except Exception as e:
                    logger.error(f"Error reading {file}: {str(e)}")

    for root, _, files in os.walk(extract_dir):
        for file in files:
            if file.lower().endswith((".txt", ".nfo", ".md")):
                 file_path = os.path.join(root, file)
                 try:
                    header = f"--- {file} ---"
                    if any(header in item for item in extracted_content):
                        continue
                        
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read(10000)
                        logger.info(f"📄 [yellow]Reading extracted doc:[/yellow] {file}", extra={"markup": True})
                        extracted_content.append(f"--- {file} (extracted) ---\n{content}")
                 except:
                    pass

    return "\n".join(extracted_content) if extracted_content else "No documentation found."

@mcp.tool()
def archive_to_mirror(local_file_path: str, ai_summary: str, metadata_tags: list[str]) -> str:
    """Upload a file to Internet Archive as a mirror."""
    logger.info(f"🚀 [bold cyan]Uploading to IA mirror:[/bold cyan] {local_file_path}", extra={"markup": True})
    if not os.path.exists(local_file_path):
        return f"Error: File {local_file_path} not found."
    
    filename = os.path.basename(local_file_path)
    clean_name = "".join(c if c.isalnum() or c in ("-", "_") else "-" for c in filename).lower()
    identifier = f"eterno-pres-{clean_name}"
    
    metadata = {
        'description': ai_summary,
        'subject': metadata_tags,
        'mediatype': 'software',
        'collection': 'opensource_software'
    }
    
    try:
        r = ia.upload(identifier, files=[local_file_path], metadata=metadata)
        if r[0].status_code == 200:
            logger.info(f"✅ [bold green]Upload complete:[/bold green] {identifier}", extra={"markup": True})
            return f"https://archive.org/details/{identifier}"
        else:
            return f"Error: Upload failed with status {r[0].status_code}"
    except Exception as e:
        logger.error(f"💥 Upload failed: {str(e)}")
        return f"Error: {str(e)}"

@mcp.tool()
def cleanup_local_storage(target: str = "all") -> str:
    """
    Clean up local storage directories.
    
    Valid targets:
    - 'all': wipes both 'data/downloads' and 'data/extracted'
    - 'downloads': wipes only 'data/downloads'
    - 'extracted': wipes only 'data/extracted'
    """
    janitor = LocalJanitor()
    downloads_path = os.path.join(BASE_DIR, "data/downloads")
    extracted_path = os.path.join(BASE_DIR, "data/extracted")
    
    cleaned = []
    if target == "all":
        janitor.wipe(downloads_path)
        janitor.wipe(extracted_path)
        cleaned = ["downloads", "extracted"]
    elif target == "downloads":
        janitor.wipe(downloads_path)
        cleaned = ["downloads"]
    elif target == "extracted":
        janitor.wipe(extracted_path)
        cleaned = ["extracted"]
    else:
        return f"Error: Invalid target '{target}'. Valid targets are 'all', 'downloads', or 'extracted'."

    targets_str = " and ".join(cleaned)
    logger.info(f"🧹 [bold green]Cleanup complete for: {targets_str}[/bold green]", extra={"markup": True})
    return f"Cleanup complete. Target(s) cleaned: {targets_str}."

if __name__ == "__main__":
    mcp.run()
