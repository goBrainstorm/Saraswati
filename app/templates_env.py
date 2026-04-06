from pathlib import Path

import jinja2
from fastapi.templating import Jinja2Templates

# Build a Jinja2 Environment with cache_size=0 to avoid the LRUCache
# dict-key bug in Python 3.14 / Jinja2 3.x under Starlette 1.x.
_TEMPLATES_DIR = Path(__file__).parent / "templates"
_jinja_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=jinja2.select_autoescape(["html"]),
    cache_size=0,  # disable bytecode cache to sidestep the LRUCache bug
)
templates = Jinja2Templates(env=_jinja_env)
