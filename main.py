# main.py
import os
import uuid
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass
import random
import math

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
from colorthief import ColorThief
import uvicorn


# --- CONFIGURATION ---
@dataclass
class Config:
    """Application configuration"""
    logo_folder: Path = Path("assets/logos")
    brand_logos_folder: Path = Path("assets/brand_logos")
    fonts_folder: Path = Path("assets/fonts")
    output_folder: Path = Path("static/thumbnails")
    canvas_width: int = 1200
    canvas_height: int = 675
    file_expiry_hours: int = 3
    
    def __post_init__(self):
        # Create directories if they don't exist
        self.logo_folder.mkdir(parents=True, exist_ok=True)
        self.brand_logos_folder.mkdir(parents=True, exist_ok=True)
        self.fonts_folder.mkdir(parents=True, exist_ok=True)
        self.output_folder.mkdir(parents=True, exist_ok=True)


config = Config()


# --- PYDANTIC MODELS ---
class ThumbnailRequest(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=10, description="Stock ticker symbol")
    stock_name: str = Field(..., min_length=1, max_length=100, description="Company name")
    prompt: str = Field(..., min_length=1, max_length=500, description="Update text/prompt")
    font_family: Optional[str] = Field(None, description="Custom font family name")
    style_preset: Optional[str] = Field("modern", description="Design style preset")


class ThumbnailResponse(BaseModel):
    image_url: str
    filename: str
    expires_at: datetime


# --- DESIGN SYSTEM ---
class DesignSystem:
    """Enhanced design system with multiple style presets"""
    
    GRADIENTS = {
        "modern": {
            "dark": [
                ((15, 23, 42), (30, 41, 59)),    # Slate
                ((31, 41, 55), (51, 65, 85)),    # Blue Gray
                ((17, 24, 39), (31, 41, 55)),    # Gray
                ((22, 30, 46), (37, 50, 72)),    # Dark Blue
            ],
            "light": [
                ((248, 250, 252), (241, 245, 249)), # Light Blue
                ((254, 252, 232), (252, 211, 77)),  # Light Yellow
                ((236, 253, 245), (167, 243, 208)), # Light Green
                ((245, 243, 255), (196, 181, 253)), # Light Purple
            ]
        },
        "corporate": {
            "dark": [
                ((30, 58, 138), (29, 78, 216)),   # Professional Blue
                ((91, 33, 182), (124, 58, 237)),  # Professional Purple
                ((6, 78, 59), (5, 150, 105)),     # Professional Green
                ((153, 27, 27), (220, 38, 38)),   # Professional Red
            ],
            "light": [
                ((255, 255, 255), (249, 250, 251)), # Clean White
                ((249, 250, 251), (243, 244, 246)), # Light Gray
                ((240, 249, 255), (219, 234, 254)), # Light Blue
                ((247, 254, 231), (220, 252, 231)), # Light Green
            ]
        },
        "vibrant": {
            "dark": [
                ((147, 51, 234), (79, 70, 229)),   # Purple to Indigo
                ((236, 72, 153), (147, 51, 234)),  # Pink to Purple
                ((34, 197, 94), (20, 184, 166)),   # Green to Teal
                ((251, 113, 133), (244, 63, 94)),  # Light Red to Red
            ],
            "light": [
                ((254, 240, 138), (251, 191, 36)), # Yellow gradient
                ((165, 243, 252), (34, 211, 238)), # Cyan gradient
                ((254, 205, 211), (251, 113, 133)), # Pink gradient
                ((196, 181, 253), (139, 92, 246)), # Purple gradient
            ]
        }
    }
    
    TYPOGRAPHY = {
        "modern": {"title_size": 72, "subtitle_size": 40, "spacing": 15},
        "corporate": {"title_size": 68, "subtitle_size": 38, "spacing": 12},
        "vibrant": {"title_size": 76, "subtitle_size": 42, "spacing": 18}
    }
    
    LAYOUTS = {
        "modern": {"logo_area_ratio": 0.35, "padding": 50, "logo_max_ratio": 0.7},
        "corporate": {"logo_area_ratio": 0.30, "padding": 40, "logo_max_ratio": 0.6},
        "vibrant": {"logo_area_ratio": 0.40, "padding": 60, "logo_max_ratio": 0.8}
    }


# --- FONT MANAGER ---
class FontManager:
    """Handles font loading and fallbacks"""
    
    DEFAULT_FONTS = {
        "bold": ["Arial-Bold.ttf", "Helvetica-Bold.ttf", "DejaVuSans-Bold.ttf"],
        "regular": ["Arial.ttf", "Helvetica.ttf", "DejaVuSans.ttf"]
    }
    
    @staticmethod
    def get_font_path(font_family: Optional[str] = None, variant: str = "regular") -> str:
        """Get font path with custom font support and fallbacks"""
        
        # Try custom font first
        if font_family:
            custom_font_path = config.fonts_folder / f"{font_family}-{variant}.ttf"
            if custom_font_path.exists():
                try:
                    ImageFont.truetype(str(custom_font_path), 10)
                    return str(custom_font_path)
                except Exception:
                    pass
        
        # Try default fonts
        for font_name in FontManager.DEFAULT_FONTS[variant]:
            font_path = config.fonts_folder / font_name
            if font_path.exists():
                try:
                    ImageFont.truetype(str(font_path), 10)
                    return str(font_path)
                except Exception:
                    continue
        
        # System fallbacks
        system_fonts = [
            "/System/Library/Fonts/Supplemental/Arial.ttf",  # macOS
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",  # Linux
            "C:/Windows/Fonts/arial.ttf"  # Windows
        ]
        
        for font_path in system_fonts:
            if os.path.exists(font_path):
                return font_path
        
        # Final fallback
        return "arial.ttf"


# --- ENHANCED THUMBNAIL GENERATOR ---
class ThumbnailGenerator:
    """Enhanced thumbnail generator with improved design logic"""
    
    def __init__(self):
        self.design_system = DesignSystem()
        self.font_manager = FontManager()
    
    def get_dominant_color(self, image_path: Path) -> Tuple[int, int, int]:
        """Extract dominant color with error handling"""
        try:
            color_thief = ColorThief(str(image_path))
            return color_thief.get_color(quality=1)
        except Exception as e:
            print(f"Could not get dominant color: {e}")
            return (128, 128, 128)
    
    def is_color_dark(self, rgb_tuple: Tuple[int, int, int]) -> bool:
        """Determine if color is dark using perceptual brightness"""
        r, g, b = rgb_tuple
        brightness = (0.299 * r + 0.587 * g + 0.114 * b)
        return brightness < 127.5
    
    def clean_title(self, prompt: str) -> str:
        """Clean and format the title text"""
        text = prompt.replace("- Intimation", "").strip()
        
        # Handle specific patterns
        if "Listing Obligations" in text:
            return "Important Update"
        
        
        return text.strip()
        # if " - " in text:
        #     parts = text.split(" - ")
        #     return parts[-1].strip()
        
        # Capitalize first letter of each word for better presentation
        return text.title()
    
    def create_gradient_background(self, img: Image.Image, start_color: Tuple[int, int, int], 
                                 end_color: Tuple[int, int, int], style: str = "linear") -> None:
        """Create enhanced gradient backgrounds"""
        draw = ImageDraw.Draw(img)
        width, height = img.size
        
        if style == "radial":
            # Radial gradient from center
            center_x, center_y = width // 2, height // 2
            max_radius = math.sqrt(center_x**2 + center_y**2)
            
            for y in range(height):
                for x in range(width):
                    distance = math.sqrt((x - center_x)**2 + (y - center_y)**2)
                    ratio = min(distance / max_radius, 1.0)
                    
                    r = int(start_color[0] + (end_color[0] - start_color[0]) * ratio)
                    g = int(start_color[1] + (end_color[1] - start_color[1]) * ratio)
                    b = int(start_color[2] + (end_color[2] - start_color[2]) * ratio)
                    
                    draw.point((x, y), (r, g, b))
        else:
            # Linear gradient (default)
            for y in range(height):
                ratio = y / height
                r = int(start_color[0] + (end_color[0] - start_color[0]) * ratio)
                g = int(start_color[1] + (end_color[1] - start_color[1]) * ratio)
                b = int(start_color[2] + (end_color[2] - start_color[2]) * ratio)
                draw.line([(0, y), (width, y)], fill=(r, g, b))
    
    def add_logo_with_effects(self, img: Image.Image, logo_path: Path, 
                            position: Tuple[int, int], max_size: int, 
                            add_shadow: bool = True, add_border: bool = False) -> None:
        """Add logo with shadow and border effects"""
        if not logo_path.exists():
            return
        
        logo = Image.open(logo_path).convert("RGBA")
        logo.thumbnail((max_size, max_size), Image.LANCZOS)
        
        x, y = position
        
        # Add shadow effect
        if add_shadow:
            shadow_offset = 8
            shadow_color = (0, 0, 0, 80)
            shadow = Image.new('RGBA', img.size, (0, 0, 0, 0))
            shadow_draw = ImageDraw.Draw(shadow)
            shadow_draw.bitmap((x + shadow_offset, y + shadow_offset), logo, fill=shadow_color)
            shadow = shadow.filter(ImageFilter.GaussianBlur(radius=10))
            img.paste(shadow, (0, 0), shadow)
        
        # Paste logo
        img.paste(logo, (x, y), logo)
        
        # Add border
        if add_border:
            draw = ImageDraw.Draw(img)
            border_size = 2
            draw.rectangle([x - border_size, y - border_size, 
                          x + logo.width + border_size, y + logo.height + border_size], 
                          outline=(200, 200, 200), width=border_size)
    
    def wrap_text(self, text: str, font: ImageFont.ImageFont, max_width: int) -> List[str]:
        """
        Wrap text to fit within specified width.
        If text contains "-", use it as a line break and remove the "-"
        """
        # Check if text contains "-" for manual line breaks
        if " - " in text:
            # Split by " - " and create lines, removing the "-"
            parts = text.split(" - ")
            lines = []
            
            draw = ImageDraw.Draw(Image.new('RGB', (1, 1)))
            
            for i, part in enumerate(parts):
                part = part.strip()
                if not part:
                    continue
                    
                # Check if this part fits in one line
                bbox = draw.textbbox((0, 0), part, font=font)
                if bbox[2] <= max_width:
                    lines.append(part)
                else:
                    # If part is too long, wrap it normally
                    words = part.split()
                    current_line = ""
                    
                    for word in words:
                        test_line = current_line + " " + word if current_line else word
                        bbox = draw.textbbox((0, 0), test_line, font=font)
                        if bbox[2] <= max_width:
                            current_line = test_line
                        else:
                            if current_line:
                                lines.append(current_line)
                            current_line = word
                    
                    if current_line:
                        lines.append(current_line)
            
            return lines
        
        # Original wrapping logic for text without "-"
        else:
            words = text.split()
            lines = []
            current_line = ""
            
            draw = ImageDraw.Draw(Image.new('RGB', (1, 1)))
            
            for word in words:
                test_line = current_line + " " + word if current_line else word
                bbox = draw.textbbox((0, 0), test_line, font=font)
                if bbox[2] <= max_width:
                    current_line = test_line
                else:
                    if current_line:
                        lines.append(current_line)
                    current_line = word
            
            if current_line:
                lines.append(current_line)
            
            return lines
    
    def generate_thumbnail(self, ticker: str, stock_name: str, prompt: str, 
                         font_family: Optional[str] = None, 
                         style_preset: str = "modern") -> str:
        """Generate thumbnail with enhanced design"""
        
        # Validate style preset
        if style_preset not in self.design_system.GRADIENTS:
            style_preset = "modern"
        
        # Setup paths
        logo_path = config.logo_folder / f"{ticker.upper()}.NSE.png"
        
        # Check for alternative logo formats
        logo_exists = False
        if logo_path.exists():
            logo_exists = True
        else:
            for ext in ['.png', '.jpg', '.jpeg', '.svg']:
                alt_path = config.logo_folder / f"{ticker.upper()}{ext}"
                if alt_path.exists():
                    logo_path = alt_path
                    logo_exists = True
                    break
        
        # Get design configuration
        typography = self.design_system.TYPOGRAPHY[style_preset]
        layout = self.design_system.LAYOUTS[style_preset]
        
        if logo_exists:
            dominant_color = self.get_dominant_color(logo_path)
            use_dark_bg = not self.is_color_dark(dominant_color)
        else:
            # Default to random color scheme when no logo
            use_dark_bg = random.choice([True, False])
        
        gradient_type = "dark" if use_dark_bg else "light"
        bg_start, bg_end = random.choice(self.design_system.GRADIENTS[style_preset][gradient_type])
        
        text_color = "#FFFFFF" if use_dark_bg else "#1F2937"
        subtitle_color = "#D1D5DB" if use_dark_bg else "#6B7280"
        
        # Create canvas
        img = Image.new("RGB", (config.canvas_width, config.canvas_height))
        
        # Create gradient background
        gradient_style = "radial" if style_preset == "vibrant" else "linear"
        self.create_gradient_background(img, bg_start, bg_end, gradient_style)
        
        if logo_exists:
            # Original layout with logo
            logo_area_width = int(config.canvas_width * layout["logo_area_ratio"])
            logo_max_size = int(logo_area_width * layout["logo_max_ratio"])
            padding = layout["padding"]
            
            # Add company logo
            logo = Image.open(logo_path).convert("RGBA")
            logo.thumbnail((logo_max_size, logo_max_size), Image.LANCZOS)
            
            logo_x = (logo_area_width - logo.width) // 2
            logo_y = (config.canvas_height - logo.height) // 2
            
            self.add_logo_with_effects(img, logo_path, (logo_x, logo_y), logo_max_size, 
                                    add_shadow=True, add_border=(style_preset == "corporate"))
            
            # Text area starts after logo
            text_area_x = logo_area_width + padding
            text_area_width = config.canvas_width - text_area_x - padding
        else:
            # Centered layout without logo
            padding = layout["padding"] * 2  # More padding for centered layout
            text_area_x = padding
            text_area_width = config.canvas_width - (padding * 2)
            
        
        # Add brand logo
        brand_logo_suffix = "WHITE" if use_dark_bg else "BLACK"
        brand_logo_path = config.brand_logos_folder / f"INVESTYWISE_{brand_logo_suffix}.png"
        
        if brand_logo_path.exists():
            brand_logo = Image.open(brand_logo_path).convert("RGBA")
            brand_logo.thumbnail((250, 125), Image.LANCZOS)
            brand_logo_x = config.canvas_width - brand_logo.width - 40
            brand_logo_y = 40
            img.paste(brand_logo, (brand_logo_x, brand_logo_y), brand_logo)
        
        # Setup text area
        # text_area_x = logo_area_width + padding
        # text_area_width = config.canvas_width - text_area_x - padding
        
        # Load fonts
        font_bold_path = self.font_manager.get_font_path(font_family, "bold")
        font_regular_path = self.font_manager.get_font_path(font_family, "regular")
        
        font_subtitle = ImageFont.truetype(font_regular_path, typography["subtitle_size"])
        font_title = ImageFont.truetype(font_bold_path, typography["title_size"])
        
        # Draw text
        draw = ImageDraw.Draw(img)
        
        if logo_exists:
            # Original positioning (left-aligned after logo)
            name_y = int(config.canvas_height * 0.25)
            draw.text((text_area_x, name_y), stock_name, fill=subtitle_color, font=font_subtitle)
            
            headline = self.clean_title(prompt)
            headline_y = name_y + typography["subtitle_size"] + 20
            
        else:
            # Centered positioning
            name_y = int(config.canvas_height * 0.35)  # More centered vertically
            
            # Center the stock name
            name_bbox = draw.textbbox((0, 0), stock_name, font=font_subtitle)
            name_width = name_bbox[2] - name_bbox[0]
            name_x = (config.canvas_width - name_width) // 2
            draw.text((name_x, name_y), stock_name, fill=subtitle_color, font=font_subtitle)
            
            headline = self.clean_title(prompt)
            headline_y = name_y + typography["subtitle_size"] + 30
        
        # Wrap text
        lines = self.wrap_text(headline, font_title, text_area_width)
        
        # Draw wrapped text
        line_height = typography["title_size"] + typography["spacing"]
        for i, line in enumerate(lines):
            y_position = headline_y + i * line_height
            
            if logo_exists:
                # Left-aligned (original behavior)
                draw.text((text_area_x, y_position), line, fill=text_color, font=font_title)
            else:
                # Center-aligned for no logo case
                line_bbox = draw.textbbox((0, 0), line, font=font_title)
                line_width = line_bbox[2] - line_bbox[0]
                line_x = (config.canvas_width - line_width) // 2
                draw.text((line_x, y_position), line, fill=text_color, font=font_title)
        
        # Generate unique filename
        unique_id = str(uuid.uuid4())[:8]
        filename = f"{ticker}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{unique_id}.png"
        output_path = config.output_folder / filename
        
        # Save image
        img.save(output_path, "PNG", quality=95, optimize=True)
        
        return filename


# --- FASTAPI APPLICATION ---
app = FastAPI(title="Thumbnail Generator API", version="1.0.0")

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Global instances
thumbnail_generator = ThumbnailGenerator()


async def cleanup_expired_files():
    """Background task to cleanup expired files"""
    current_time = datetime.now()
    
    for file_path in config.output_folder.glob("*.png"):
        file_age = current_time - datetime.fromtimestamp(file_path.stat().st_mtime)
        if file_age > timedelta(hours=config.file_expiry_hours):
            try:
                file_path.unlink()
                print(f"Deleted expired file: {file_path.name}")
            except Exception as e:
                print(f"Error deleting file {file_path.name}: {e}")


@app.on_event("startup")
async def startup_event():
    """Startup tasks"""
    # Schedule cleanup task
    asyncio.create_task(periodic_cleanup())


async def periodic_cleanup():
    """Periodic cleanup of expired files"""
    while True:
        await cleanup_expired_files()
        await asyncio.sleep(3600)  # Run every hour


@app.post("/generate-thumbnail", response_model=ThumbnailResponse)
async def generate_thumbnail(request: ThumbnailRequest, background_tasks: BackgroundTasks):
    """Generate a thumbnail image"""
    try:
        filename = thumbnail_generator.generate_thumbnail(
            ticker=request.ticker.upper(),
            stock_name=request.stock_name,
            prompt=request.prompt,
            font_family=request.font_family,
            style_preset=request.style_preset or "modern"
        )
        
        # Schedule cleanup
        background_tasks.add_task(cleanup_expired_files)
        
        # Calculate expiry time
        expires_at = datetime.now() + timedelta(hours=config.file_expiry_hours)
        
        image_url = f"/static/thumbnails/{filename}"
        
        return ThumbnailResponse(
            image_url=image_url,
            filename=filename,
            expires_at=expires_at
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/thumbnail/{filename}")
async def get_thumbnail(filename: str):
    """Serve thumbnail file"""
    file_path = config.output_folder / filename
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    
    # Check if file has expired
    file_age = datetime.now() - datetime.fromtimestamp(file_path.stat().st_mtime)
    if file_age > timedelta(hours=config.file_expiry_hours):
        file_path.unlink()  # Delete expired file
        raise HTTPException(status_code=410, detail="Thumbnail has expired")
    
    return FileResponse(file_path, media_type="image/png")


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.now()}


@app.get("/")
async def root():
    """Root endpoint with API information"""
    return {
        "message": "Thumbnail Generator API",
        "version": "1.0.0",
        "endpoints": {
            "generate": "/generate-thumbnail",
            "get_image": "/thumbnail/{filename}",
            "health": "/health"
        },
        "supported_styles": list(DesignSystem.GRADIENTS.keys())
    }


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)