# code/handlers/file_operations/processors/__init__.py
from .base_processor import BaseProcessor
from .audio import AudioProcessor
from .image import ImageProcessor
from .document import DocumentProcessor
from .table import TableProcessor
from .text import TextFileProcessor

__all__ = [
    'BaseProcessor',
    'AudioProcessor',
    'ImageProcessor', 
    'DocumentProcessor',
    'TableProcessor',
    'TextFileProcessor'
]