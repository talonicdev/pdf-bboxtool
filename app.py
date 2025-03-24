#!/usr/bin/env python3
import tkinter as tk
from tkinter import filedialog, simpledialog, messagebox
from tkinter import ttk
from PIL import Image, ImageTk
from pdf2image import convert_from_path
import json, datetime, os, hashlib, io, zipfile

# ------------------------- CONSTANTS -------------------------
APP_NAME = "PDF Bounding Box Annotation Tool"
DEFAULT_TITLE = "Annotation Tool"
DEFAULT_LABEL = "No Label"
JSON_FILETYPES = [("JSON Files", "*.json")]
PDF_FILETYPES = [("PDF Files", "*.pdf")]

MIN_DRAG_THRESHOLD = 5      # pixels; below this, a click is treated as a simple deselection
ANCHOR_SIZE = 8             # size (in pixels) of the resize anchor
DEFAULT_DPI = 300           # default DPI for PDF conversion
TOOLTIP_DELAY = 500         # tooltip delay in ms
BOX_SELECTED_WIDTH = 4
BOX_UNSELECTED_WIDTH = 2
INITIAL_WINDOW_SIZE = "1200x800"

# For bounding-box colors, cycle through if no color is assigned yet for a label
COLOR_CYCLE = [
    "red", "blue", "green", "orange", "purple", "yellow", "grey", "cyan",
    "pink", "light sea green", "IndianRed1", "dark khaki"
]

# ------------------------- Tooltip class -------------------------
class CreateToolTip(object):
    """
    Create a tooltip for a given widget.
    """
    def __init__(self, widget, text='widget info'):
        self.widget = widget
        self.text = text
        self.tipwindow = None
        self.id = None
        widget.bind("<Enter>", self.enter)
        widget.bind("<Leave>", self.leave)

    def enter(self, event=None):
        self.schedule()

    def leave(self, event=None):
        self.unschedule()
        self.hidetip()

    def schedule(self):
        self.unschedule()
        self.id = self.widget.after(TOOLTIP_DELAY, self.showtip)

    def unschedule(self):
        id_ = self.id
        self.id = None
        if id_:
            self.widget.after_cancel(id_)

    def showtip(self, event=None):
        try:
            x, y, cx, cy = self.widget.bbox("insert")
        except Exception:
            x, y, cx, cy = 0, 0, 0, 0
        x = x + self.widget.winfo_rootx() + 25
        y = y + cy + self.widget.winfo_rooty() + 25
        self.tipwindow = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry("+%d+%d" % (x, y))
        label = tk.Label(
            tw, text=self.text, justify=tk.LEFT,
            background="#ffffe0", relief=tk.SOLID, borderwidth=1,
            font=("tahoma", "8", "normal")
        )
        label.pack(ipadx=1)

    def hidetip(self):
        tw = self.tipwindow
        self.tipwindow = None
        if tw:
            tw.destroy()

# ------------------------- MD5 HELPER -------------------------
def md5_checksum(file_path):
    if not file_path or not os.path.exists(file_path):
        return None
    hash_md5 = hashlib.md5()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    except Exception:
        return None

# ------------------------- BOUNDING BOX -------------------------
class BoundingBox:
    """
    A bounding-box object for one region in the PDF.
    """
    def __init__(self, canvas, x1, y1, x2, y2, label=DEFAULT_LABEL):
        self.canvas = canvas
        self.orig_coords = [x1, y1, x2, y2]   # in original PDF-image coords
        self.label = label
        self.properties = {}
        self.rect_id = None
        self.text_id = None
        self.anchor_id = None
        self.selected = False

    def draw(self, scale, color):
        """
        Draw (or redraw) the bounding box at the current scale,
        using the given color.
        """
        s_coords = [coord * scale for coord in self.orig_coords]
        width = BOX_SELECTED_WIDTH if self.selected else BOX_UNSELECTED_WIDTH

        # Rectangle
        if self.rect_id is None:
            self.rect_id = self.canvas.create_rectangle(
                *s_coords,
                outline=color,
                width=width,
                fill=color,
                stipple="gray50",
                tags=("bbox_rect",)
            )
        else:
            self.canvas.coords(self.rect_id, *s_coords)
            self.canvas.itemconfig(self.rect_id, width=width, fill=color, stipple="gray50", outline=color)

        # Label text
        text_x = (s_coords[0] + s_coords[2]) / 2
        text_y = s_coords[1] - 10
        display_text = f"{self.label}"
        if self.text_id is None:
            self.text_id = self.canvas.create_text(text_x, text_y, text=display_text, fill="black")
        else:
            self.canvas.coords(self.text_id, text_x, text_y)
            self.canvas.itemconfig(self.text_id, text=display_text)

        # Resize anchor if selected
        if self.selected:
            anchor_x = s_coords[2]
            anchor_y = s_coords[3]
            if self.anchor_id is None:
                self.anchor_id = self.canvas.create_rectangle(
                    anchor_x - ANCHOR_SIZE, anchor_y - ANCHOR_SIZE,
                    anchor_x, anchor_y,
                    fill="black",
                    tags=("anchor",)
                )
            else:
                self.canvas.coords(
                    self.anchor_id,
                    anchor_x - ANCHOR_SIZE, anchor_y - ANCHOR_SIZE,
                    anchor_x, anchor_y
                )
        else:
            if self.anchor_id:
                self.canvas.delete(self.anchor_id)
                self.anchor_id = None

    def is_inside(self, x, y, scale):
        s_coords = [coord * scale for coord in self.orig_coords]
        return s_coords[0] <= x <= s_coords[2] and s_coords[1] <= y <= s_coords[3]

    def is_on_anchor(self, x, y, scale):
        s_coords = [coord * scale for coord in self.orig_coords]
        ax1 = s_coords[2] - ANCHOR_SIZE
        ay1 = s_coords[3] - ANCHOR_SIZE
        ax2 = s_coords[2]
        ay2 = s_coords[3]
        return ax1 <= x <= ax2 and ay1 <= y <= ay2

    def move(self, dx, dy, scale):
        d_orig_x = dx / scale
        d_orig_y = dy / scale
        self.orig_coords[0] += d_orig_x
        self.orig_coords[1] += d_orig_y
        self.orig_coords[2] += d_orig_x
        self.orig_coords[3] += d_orig_y

# ------------------------- COLLAPSIBLE FRAME FOR PROPERTIES -------------------------
class CollapsiblePropertyFrame(tk.Frame):
    def __init__(self, parent, property_name, values, on_values_changed, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        self.property_name = property_name
        self.values = values
        self.on_values_changed = on_values_changed
        self.collapsed = False

        # Remove border highlight from frame
        self.config(bd=0, highlightthickness=0)

        # Header with collapse button and property label
        self.header_frame = tk.Frame(self, bd=0, highlightthickness=0)
        self.header_frame.pack(fill=tk.X)
        self.toggle_button = tk.Button(self.header_frame, text="[-]", width=3, command=self.toggle)
        self.toggle_button.pack(side=tk.LEFT)
        lbl = tk.Label(self.header_frame, text=self.property_name, font=("Arial", 10, "bold"))
        lbl.pack(side=tk.LEFT)

        # Body frame (where listbox and buttons go)
        self.body_frame = tk.Frame(self, bd=0, highlightthickness=0)
        self.body_frame.pack(fill=tk.BOTH, expand=True)

        # The listbox with possible values
        self.value_listbox = tk.Listbox(self.body_frame, bd=0, highlightthickness=0)
        self.value_listbox.pack(fill=tk.BOTH, expand=True)

        for val in self.values:
            self.value_listbox.insert(tk.END, val)

        # Add/Edit/Del buttons
        btn_frame = tk.Frame(self.body_frame, bd=0, highlightthickness=0)
        btn_frame.pack(fill=tk.X)
        tk.Button(btn_frame, text="Add", command=self.add_value).pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Button(btn_frame, text="Edit", command=self.edit_value).pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Button(btn_frame, text="Del", command=self.delete_value).pack(side=tk.LEFT, fill=tk.X, expand=True)

    def toggle(self):
        """Collapse/expand the property frame."""
        self.collapsed = not self.collapsed
        if self.collapsed:
            self.body_frame.forget()
            self.toggle_button.config(text="[+]")
        else:
            self.body_frame.pack(fill=tk.BOTH, expand=True)
            self.toggle_button.config(text="[-]")

    def add_value(self):
        new_val = simpledialog.askstring("Add Value", f"Enter new value for '{self.property_name}':", parent=self)
        if new_val:
            if new_val not in self.values:
                self.values.append(new_val)
                self.value_listbox.insert(tk.END, new_val)
                self.on_values_changed()

    def edit_value(self):
        selection = self.value_listbox.curselection()
        if not selection:
            return
        index = selection[0]
        old_val = self.value_listbox.get(index)
        new_val = simpledialog.askstring("Edit Value", f"Edit value for '{self.property_name}':", initialvalue=old_val, parent=self)
        if new_val and new_val != old_val:
            if new_val not in self.values:
                self.values.remove(old_val)
                self.values.append(new_val)
                self.value_listbox.delete(index)
                self.value_listbox.insert(index, new_val)
                self.on_values_changed()

    def delete_value(self):
        selection = self.value_listbox.curselection()
        if not selection:
            return
        index = selection[0]
        old_val = self.value_listbox.get(index)
        confirm = messagebox.askyesno("Delete Value", f"Are you sure you want to delete '{old_val}'?")
        if confirm:
            self.values.remove(old_val)
            self.value_listbox.delete(index)
            self.on_values_changed()

# ------------------------- BBOX EDIT DIALOG (LABEL + PROPERTIES) -------------------------
class AutocompleteEntry(tk.Entry):
    def set_completion_list(self, completion_list):
        self._completion_list = sorted(completion_list, key=str.lower)
        self._hits = []
        self._hit_index = 0
        self.position = 0
        self.bind('<KeyRelease>', self.handle_keyrelease)

    def autocomplete(self, delta=0):
        if delta:
            self.delete(self.position, tk.END)
        else:
            self.position = len(self.get())
        _hits = [e for e in self._completion_list if e.lower().startswith(self.get().lower())]
        if _hits != self._hits:
            self._hit_index = 0
            self._hits = _hits
        if self._hits:
            self._hit_index = (self._hit_index + delta) % len(self._hits)
            self.delete(0, tk.END)
            self.insert(0, self._hits[self._hit_index])
            self.select_range(self.position, tk.END)

    def handle_keyrelease(self, event):
        if event.state & (0x0004 | 0x0001 | 0x20000):
            return
        if event.keysym == "BackSpace":
            self.delete(self.index(tk.INSERT), tk.END)
            self.position = self.index(tk.END)
        elif event.keysym == "Left":
            if self.position < self.index(tk.END):
                self.delete(self.position, tk.END)
            else:
                self.position -= 1
                self.delete(self.position, tk.END)
        elif event.keysym == "Right":
            self.position = self.index(tk.END)
        elif event.keysym in ("Down", "Up"):
            self.autocomplete(1 if event.keysym=="Down" else -1)
        else:
            self.autocomplete()

class AutocompleteCombobox(ttk.Combobox):
    def set_completion_list(self, completion_list):
        self._completion_list = sorted(completion_list, key=str.lower)
        self._hits = []
        self._hit_index = 0
        self.position = 0
        self['values'] = self._completion_list
        self.bind('<KeyRelease>', self.handle_keyrelease)

    def autocomplete(self, delta=0):
        if delta:
            self.delete(self.position, tk.END)
        else:
            self.position = len(self.get())
        _hits = [e for e in self._completion_list if e.lower().startswith(self.get().lower())]
        if _hits != self._hits:
            self._hit_index = 0
            self._hits = _hits
        if self._hits:
            self._hit_index = (self._hit_index + delta) % len(self._hits)
            self.delete(0, tk.END)
            self.insert(0, self._hits[self._hit_index])
            self.select_range(self.position, tk.END)

    def handle_keyrelease(self, event):
        if event.state & (0x0004 | 0x0001 | 0x20000):
            return
        if event.keysym == "BackSpace":
            self.delete(self.index(tk.INSERT), tk.END)
            self.position = self.index(tk.END)
        elif event.keysym == "Left":
            if self.position < self.index(tk.END):
                self.delete(self.position, tk.END)
            else:
                self.position -= 1
                self.delete(self.position, tk.END)
        elif event.keysym == "Right":
            self.position = self.index(tk.END)
        elif event.keysym in ("Down", "Up"):
            self.autocomplete(1 if event.keysym=="Down" else -1)
        else:
            self.autocomplete()

class EditBBoxDialog(simpledialog.Dialog):
    def __init__(self, parent, title, bbox, properties_dict, on_properties_changed):
        """
        :param parent: the root app
        :param title: dialog title
        :param bbox: the bounding box being edited
        :param properties_dict: { propName: [possibleValue1, ...], ... }
        :param on_properties_changed: callback to rebuild property frames, etc.
        """
        self.bbox = bbox
        self.properties_dict = properties_dict
        self.on_properties_changed = on_properties_changed
        super().__init__(parent, title=title)

    def body(self, master):
        # -- Row 0: Label --
        tk.Label(master, text="Label:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        self.label_entry = AutocompleteEntry(master)
        self.label_entry.set_completion_list(list(self.parent.label_color_map.keys()))
        self.label_entry.grid(row=0, column=1, padx=5, pady=5)
        self.label_entry.insert(0, self.bbox.label)

        # Show a combobox for each property
        self.comboboxes = {}
        row = 1
        sorted_props = sorted(self.properties_dict.keys())
        for prop_name in sorted_props:
            tk.Label(master, text=f"{prop_name}:").grid(row=row, column=0, sticky=tk.W, padx=5, pady=5)
            values = self.properties_dict[prop_name]
            combo = AutocompleteCombobox(master)
            combo.set_completion_list(values)
            current_val = self.bbox.properties.get(prop_name, "")
            combo.set(current_val)
            combo.grid(row=row, column=1, padx=5, pady=5)

            self.comboboxes[prop_name] = combo
            row += 1

        return self.label_entry

    def apply(self):
        self.bbox.label = self.label_entry.get().strip()
        for prop_name, combo in self.comboboxes.items():
            val = combo.get().strip()
            # If user typed something new, add it to the global list
            if val and val not in self.properties_dict[prop_name]:
                self.properties_dict[prop_name].append(val)
            if val:
                self.bbox.properties[prop_name] = val
            else:
                self.bbox.properties.pop(prop_name, None)
                
        self.on_properties_changed()

# ------------------------- MAIN APPLICATION -------------------------
class PDFAnnotationTool(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)

        self.geometry(INITIAL_WINDOW_SIZE)

        self.active_page = 1

        # We'll wait until we've packed everything, then adjust the side pane to its min size
        self.after(10, self.set_initial_sidebar_size)

        self.unsaved_changes = False
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self.pdf_file = None
        self.images = []
        self.original_page = None
        self.scaled_page = None
        self.current_page_tk = None
        self.annotations = {}         # { page_number: [BoundingBox, ...] }
        self.label_color_map = {}     # label -> color
        self.color_index = 0

        self.current_dpi = DEFAULT_DPI
        self.current_checksum = None

        self.zoom = 1.0
        self.selected_bbox = None
        self.moving = False
        self.move_start_x = None
        self.move_start_y = None
        self.drawing = False
        self.start_x = None
        self.start_y = None
        self.temp_rect = None
        self.resizing = False
        self.resize_start_x = None
        self.resize_start_y = None
        self.resize_initial_br = None

        self.last_save_path = None

        self.properties_dict = {}

        self.create_widgets()
        self.update_title()

    def set_initial_sidebar_size(self):
        # TODO: Resize sidebar to min size by moving to ttk or finding some alternative
        # self.paned.sashpos(0, 150) # '0' for the first sash, '150' for the desired position
        pass

    def update_title(self):
        base = DEFAULT_TITLE
        self.title(APP_NAME + (" *" if self.unsaved_changes else ""))

    def mark_unsaved(self):
        self.unsaved_changes = True
        self.update_title()

    def mark_saved(self):
        self.unsaved_changes = False
        self.update_title()

    def on_close(self):
        if self.unsaved_changes:
            resp = messagebox.askyesnocancel("Unsaved Changes", "You have unsaved changes. Save before exiting?")
            if resp is None:
                return
            if resp:
                self.save()
                if self.unsaved_changes:
                    return
        self.destroy()

    def resize_prop_inner_frame(self, event):
        self.prop_canvas.itemconfig(self.prop_window, width=event.width)

    def create_widgets(self):
        # Menubar
        menubar = tk.Menu(self)
        filemenu = tk.Menu(menubar, tearoff=0)
        filemenu.add_command(label="Open PDF", command=self.open_pdf)
        filemenu.add_command(label="Load Annotations", command=self.load_annotations)
        filemenu.add_separator()
        filemenu.add_command(label="Save", command=self.save)
        filemenu.add_command(label="Save as..", command=self.save_as)
        menubar.add_cascade(label="File", menu=filemenu)

        exportmenu = tk.Menu(menubar, tearoff=0)
        exportmenu.add_command(label="Export image", command=self.export_image)
        exportmenu.add_command(label="Export all images", command=self.export_all_images)
        exportmenu.add_command(label="Export bboxes", command=self.export_bboxes)
        menubar.add_cascade(label="Export", menu=exportmenu)
        self.config(menu=menubar)

        # Paned window: left sidebar + main area
        self.paned = tk.PanedWindow(self, orient=tk.HORIZONTAL, sashrelief=tk.RAISED, sashwidth=5, width=10)
        self.paned.pack(fill=tk.BOTH, expand=True)

        # -------------- SIDEBAR --------------
        # We'll place a vertical paned window inside so the top portion can be pages,
        # the middle portion can be properties, and the bottom portion can be bounding boxes.
        self.sidebar = tk.Frame(self.paned, width=200)
        self.paned.add(self.sidebar, minsize=150)  # user can drag to expand from min 150 px

        dpi_frame = tk.Frame(self.sidebar)
        dpi_frame.pack(fill=tk.X, pady=5)
        tk.Label(dpi_frame, text="DPI:").pack(side=tk.LEFT)
        self.dpi_var = tk.IntVar(value=self.current_dpi)
        self.dpi_entry = tk.Entry(dpi_frame, textvariable=self.dpi_var, width=5)
        self.dpi_entry.pack(side=tk.LEFT)
        tk.Button(dpi_frame, text="Set", command=self.on_dpi_change).pack(side=tk.LEFT)
        CreateToolTip(self.dpi_entry, "Enter desired DPI and click Set.")

        self.sidebar_paned = tk.PanedWindow(self.sidebar, orient=tk.VERTICAL, sashrelief=tk.RAISED, sashwidth=5)
        self.sidebar_paned.pack(fill=tk.BOTH, expand=True)

        # Pages Frame (top)
        self.pages_frame = tk.Frame(self.sidebar_paned, bd=0, highlightthickness=0)
        self.sidebar_paned.add(self.pages_frame, minsize=50, stretch="always")

        tk.Label(self.pages_frame, text="Pages:").pack(fill=tk.X)
        self.page_listbox = tk.Listbox(self.pages_frame, bd=0, highlightthickness=0)
        self.page_listbox.pack(fill=tk.BOTH, expand=True)
        self.page_listbox.bind("<<ListboxSelect>>", self.on_page_select)
        CreateToolTip(self.page_listbox, "Select a page to view.")
        self.current_page_label = tk.Label(self.pages_frame, text="Current Page: --", fg="dimgray")
        self.current_page_label.pack(fill=tk.X, pady=(2, 0))
        ttk.Separator(self.pages_frame, orient="horizontal").pack(fill="x", pady=(2, 5))

        # Properties Panel (middle)
        self.properties_panel = tk.Frame(self.sidebar_paned, bd=0, highlightthickness=0)
        self.sidebar_paned.add(self.properties_panel, stretch="always")

        tk.Label(self.properties_panel, text="Properties:").pack(fill=tk.X)
        
        # A canvas + scrollbar for the collapsible frames
        prop_container = tk.Frame(self.properties_panel)
        prop_container.pack(fill=tk.BOTH, expand=True)

        self.prop_canvas = tk.Canvas(prop_container, bd=0, highlightthickness=0)
        self.prop_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.prop_scrollbar = tk.Scrollbar(prop_container, orient=tk.VERTICAL, command=self.prop_canvas.yview)
        self.prop_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.prop_canvas.configure(yscrollcommand=self.prop_scrollbar.set)

        self.prop_inner_frame = tk.Frame(self.prop_canvas, bd=0, highlightthickness=0)
        self.prop_canvas.bind("<Configure>", self.resize_prop_inner_frame)
        self.prop_window = self.prop_canvas.create_window((0, 0), window=self.prop_inner_frame, anchor="nw")

        tk.Button(self.properties_panel, text="Add Property", command=self.add_new_property).pack(fill=tk.X, pady=5)


        # Bounding Boxes Frame (bottom)
        self.bbox_frame = tk.Frame(self.sidebar_paned, bd=0, highlightthickness=0)
        self.sidebar_paned.add(self.bbox_frame, minsize=10, stretch="never")

        tk.Label(self.bbox_frame, text="Bounding Boxes:").pack(fill=tk.X)
        self.bbox_listbox = tk.Listbox(self.bbox_frame, bd=0, highlightthickness=0)
        self.bbox_listbox.pack(fill=tk.BOTH, expand=True)
        self.bbox_listbox.bind("<<ListboxSelect>>", self.on_bbox_list_select)
        self.bbox_listbox.bind("<Double-Button-1>", self.edit_bbox_dialog)
        self.bbox_listbox.bind("<Button-3>", self.on_bbox_list_right_click)
        CreateToolTip(self.bbox_listbox, "Select a bounding box. Double-click to edit, right-click to delete.")

        # Coord label at the very bottom of the sidebar
        self.coord_label = tk.Label(self.sidebar, text="", fg="dimgray", justify=tk.LEFT, height=3)
        self.coord_label.pack(fill=tk.X)

        # -------------- MAIN DISPLAY (Canvas) --------------
        self.main_frame = tk.Frame(self.paned)
        self.paned.add(self.main_frame, stretch="always")

        self.canvas_frame = tk.Frame(self.main_frame)
        self.canvas_frame.pack(fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(self.canvas_frame, bg="gray")
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.vbar = tk.Scrollbar(self.canvas_frame, orient=tk.VERTICAL, command=self.canvas.yview)
        self.vbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.hbar = tk.Scrollbar(self.main_frame, orient=tk.HORIZONTAL, command=self.canvas.xview)
        self.hbar.pack(side=tk.BOTTOM, fill=tk.X)
        self.canvas.configure(yscrollcommand=self.vbar.set, xscrollcommand=self.hbar.set, cursor="crosshair")

        # Canvas bindings
        self.canvas.bind("<ButtonPress-1>", self.on_canvas_mouse_down)
        self.canvas.bind("<B1-Motion>", self.on_canvas_mouse_move)
        self.canvas.bind("<ButtonRelease-1>", self.on_canvas_mouse_up)
        self.canvas.bind("<MouseWheel>", self.on_mousewheel)
        self.canvas.bind("<Button-4>", self.on_mousewheel)  # Linux scroll up
        self.canvas.bind("<Button-5>", self.on_mousewheel)  # Linux scroll down
        self.canvas.bind("<Button-3>", self.on_canvas_right_click)
        self.canvas.bind("<Motion>", self.on_canvas_motion)
        self.canvas.tag_bind("bbox_rect", "<Enter>", lambda e: self.canvas.config(cursor="fleur"))
        self.canvas.tag_bind("bbox_rect", "<Leave>", lambda e: self.canvas.config(cursor="crosshair"))
        self.canvas.tag_bind("anchor", "<Enter>", lambda e: self.canvas.config(cursor="bottom_right_corner"))
        self.canvas.tag_bind("anchor", "<Leave>", lambda e: self.canvas.config(cursor="crosshair"))

        # Build out the property frames in the panel
        self.build_property_frames()

    def on_properties_frame_configure(self):
        # Update the scrollregion to encompass the entire inner frame
        self.prop_canvas.config(scrollregion=self.prop_canvas.bbox("all"))

    def add_new_property(self):
        prop_name = simpledialog.askstring("Add Property", "Enter new property name:", parent=self)
        if prop_name:
            # Clean up name
            prop_name = prop_name.strip()
            if prop_name and prop_name not in self.properties_dict:
                self.properties_dict[prop_name] = []
                self.build_property_frames()
                self.mark_unsaved()
            elif prop_name:
                messagebox.showinfo("Duplicate", f"Property '{prop_name}' already exists.")

    def build_property_frames(self):
        for child in self.prop_inner_frame.winfo_children():
            child.destroy()

        if not self.properties_dict:
            lbl = tk.Label(self.prop_inner_frame, text="No properties yet", fg="dark gray")
            lbl.pack(fill=tk.X, padx=10, pady=10)
            return

        # Sort property names so they appear alphabetically
        for pname in sorted(self.properties_dict.keys()):
            values_ref = self.properties_dict[pname]
            frame = CollapsiblePropertyFrame(
                self.prop_inner_frame,
                pname,
                values_ref,
                on_values_changed=self.on_property_values_changed
            )
            frame.pack(fill=tk.X)

        # Force refresh
        self.prop_canvas.update_idletasks()
        self.prop_canvas.config(scrollregion=self.prop_canvas.bbox("all"))

    def on_property_values_changed(self):
        """Callback whenever a property's value list is changed."""
        self.mark_unsaved()

    # ----------------------- PDF LOADING -----------------------
    def open_pdf(self):
        file_path = filedialog.askopenfilename(filetypes=PDF_FILETYPES)
        if not file_path:
            return
        self.pdf_file = file_path
        dpi = self.dpi_var.get() if hasattr(self, 'dpi_var') else DEFAULT_DPI
        self.current_dpi = dpi
        self.current_checksum = md5_checksum(self.pdf_file)
        try:
            self.images = convert_from_path(self.pdf_file, dpi=dpi)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to convert PDF: {e}")
            return
        self.annotations = {}
        self.page_listbox.delete(0, tk.END)
        for i, _ in enumerate(self.images):
            self.page_listbox.insert(tk.END, f" Page {i+1}")
            self.annotations[i+1] = []
        self.last_save_path = None
        self.mark_saved()
        self.show_page(1)
        self.page_listbox.selection_set(0)

    def on_dpi_change(self):
        try:
            new_dpi = int(self.dpi_var.get())
        except ValueError:
            messagebox.showerror("Error", "Please enter a valid DPI value.")
            return
        if self.current_dpi is None:
            self.current_dpi = new_dpi
            return
        if new_dpi == self.current_dpi:
            return
        # Rescale existing bounding boxes
        factor = new_dpi / self.current_dpi
        for page in self.annotations:
            for bbox in self.annotations[page]:
                bbox.orig_coords = [coord * factor for coord in bbox.orig_coords]
        self.current_dpi = new_dpi
        try:
            self.images = convert_from_path(self.pdf_file, dpi=new_dpi)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to convert PDF at new DPI: {e}")
            return
        self.show_page(self.current_page_num)
        self.mark_unsaved()

    # ----------------------- ANNOTATIONS LOADING -----------------------
    def load_annotations(self):
        file_path = filedialog.askopenfilename(filetypes=JSON_FILETYPES)
        if not file_path:
            return
        try:
            with open(file_path, "r") as f:
                data = json.load(f)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load JSON: {e}")
            return

        new_pdf = data.get("filename", None)
        saved_checksum = data.get("checksum", None)
        saved_dpi = data.get("dpi", None)

        # If there's a "properties" dict, load it
        if "properties" in data:
            self.properties_dict = data["properties"]
        else:
            self.properties_dict = {}
            for page_data in data.get("pages", []):
                for bbox_data in page_data.get("bboxes", []):
                    for pa in bbox_data.get("properties", []):
                        pname = pa.get("property")
                        pval = pa.get("value", "").strip()
                        if not pname:
                            continue
                        vals = self.properties_dict.setdefault(pname, [])
                        if pval and pval not in vals:
                            vals.append(pval)
        self.build_property_frames()

        if new_pdf and os.path.exists(new_pdf):
            current_checksum = md5_checksum(new_pdf)
            if not self.pdf_file or (self.pdf_file != new_pdf) or (current_checksum != saved_checksum):
                if self.pdf_file and ((self.pdf_file != new_pdf) or (current_checksum != saved_checksum)):
                    resp = messagebox.askyesnocancel(
                        "PDF Mismatch",
                        "The annotations file references a PDF that may differ.\n"
                        "Yes: Load that PDF.\n"
                        "No: Keep current PDF.\n"
                        "Cancel: Abort loading."
                    )
                    if resp is None:
                        return
                else:
                    resp = True
                    
                if resp:
                    self.pdf_file = new_pdf
                    self.current_checksum = current_checksum
                    if saved_dpi:
                        self.current_dpi = saved_dpi
                        self.dpi_var.set(self.current_dpi)
                    try:
                        self.images = convert_from_path(self.pdf_file, dpi=self.current_dpi)
                    except Exception as e:
                        messagebox.showerror("Error", f"Failed to convert PDF: {e}")
                        return

        # If we have no PDF loaded or no valid path, user can still have bounding boxes
        if not self.pdf_file or not self.images:
            self.annotations = {}
            messagebox.showinfo("Info", "Annotations loaded, but no PDF is open.")
        else:
            # Rebuild pages list
            self.page_listbox.delete(0, tk.END)
            for i, _ in enumerate(self.images):
                self.page_listbox.insert(tk.END, f" Page {i+1}")
            self.annotations = {i+1: [] for i in range(len(self.images))}

        # Load bounding boxes
        for page_data in data.get("pages", []):
            page_num = page_data.get("page")
            if page_num not in self.annotations:
                continue
            for bbox_data in page_data.get("bboxes", []):
                coords = bbox_data.get("bbox", [0, 0, 0, 0])
                label = bbox_data.get("label", DEFAULT_LABEL)
                props_array = bbox_data.get("properties", [])
                new_bbox = BoundingBox(self.canvas, *coords, label=label)
                prop_dict = {}
                for pa in props_array:
                    p_name = pa.get("property")
                    p_val = pa.get("value", "")
                    if p_name:
                        prop_dict[p_name] = p_val
                new_bbox.properties = prop_dict
                self.annotations[page_num].append(new_bbox)

        if saved_dpi and saved_dpi != self.current_dpi:
            self.current_dpi = saved_dpi
            self.dpi_var.set(self.current_dpi)
            try:
                if self.pdf_file:
                    self.images = convert_from_path(self.pdf_file, dpi=saved_dpi)
            except Exception as e:
                messagebox.showerror("Error", f"Failed to convert PDF at new DPI: {e}")
                return

        if self.images:
            self.page_listbox.selection_set(0)
            self.show_page(1)

        self.last_save_path = file_path
        self.mark_saved()

    def _save_annotations_to(self, save_path):
        data = {
            "filename": self.pdf_file,
            "date": datetime.datetime.now().isoformat(),
            "checksum": md5_checksum(self.pdf_file),
            "dpi": self.current_dpi,
            "properties": self.properties_dict,
            "pages": []
        }
        for page_num, boxes in self.annotations.items():
            page_data = {"page": page_num, "bboxes": []}
            if self.images:
                img = self.images[page_num - 1]
                dimensions = {"width": img.width, "height": img.height}
                page_data["dimensions"] = dimensions

            for box in boxes:
                coords = [round(c, 2) for c in box.orig_coords]
                props_array = []
                for p_name, p_val in box.properties.items():
                    props_array.append({"property": p_name, "value": p_val})
                page_data["bboxes"].append({
                    "label": box.label,
                    "bbox": coords,
                    "properties": props_array
                })
            data["pages"].append(page_data)

        try:
            with open(save_path, "w") as f:
                json.dump(data, f, indent=2)
            messagebox.showinfo("Saved", "Annotations saved successfully.")
            self.mark_saved()
            self.last_save_path = save_path
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save annotations: {e}")

    def save(self):
        if self.last_save_path:
            self._save_annotations_to(self.last_save_path)
        else:
            self.save_as()

    def save_as(self):
        save_path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=JSON_FILETYPES)
        if not save_path:
            return
        self._save_annotations_to(save_path)

    def export_image(self):
        if not self.original_page:
            messagebox.showerror("Error", "No page loaded.")
            return
        save_path = filedialog.asksaveasfilename(
            title="Save image as..",
            filetypes=[("PNG files", "*.png")],
            defaultextension=".png"
        )
        if not save_path:
            return
        try:
            self.original_page.save(save_path, format="PNG")
            messagebox.showinfo("Export", "Image exported successfully.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to export image: {e}")

    def export_all_images(self):
        if not self.images:
            messagebox.showerror("Error", "No PDF loaded.")
            return
        zip_buffer = io.BytesIO()
        try:
            with zipfile.ZipFile(zip_buffer, mode='w', compression=zipfile.ZIP_DEFLATED) as zip_file:
                for i, page in enumerate(self.images):
                    img_bytes = io.BytesIO()
                    page.save(img_bytes, format="PNG")
                    img_bytes.seek(0)
                    zip_file.writestr(f"{i+1:02}.png", img_bytes.read())
            zip_buffer.seek(0)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to create zip: {e}")
            return

        default_zip_name = "images.zip"
        if self.pdf_file:
            pdf_stem = os.path.splitext(os.path.basename(self.pdf_file))[0]
            default_zip_name = pdf_stem + ".images.zip"

        save_path = filedialog.asksaveasfilename(
            title="Save zip file as..",
            filetypes=[("ZIP file", ".zip")],
            initialfile=default_zip_name
        )
        if not save_path:
            return
        try:
            with open(save_path, 'wb') as f:
                f.write(zip_buffer.read())
            messagebox.showinfo("Export", "All images exported successfully.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to export zip: {e}")

    def export_bboxes(self):
        bboxes_all = []
        labels_all = []
        for page in sorted(self.annotations):
            for bbox in self.annotations[page]:
                bboxes_all.append(bbox.orig_coords)
                labels_all.append(bbox.label)
        data = {"bboxes": bboxes_all, "labels": labels_all}
        save_path = filedialog.asksaveasfilename(
            title="Export bboxes as JSON",
            filetypes=JSON_FILETYPES,
            defaultextension=".json"
        )
        if not save_path:
            return
        try:
            with open(save_path, "w") as f:
                json.dump(data, f, indent=2)
            messagebox.showinfo("Export", "Bounding boxes exported successfully.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to export bounding boxes: {e}")

    # ----------------------- PAGE SELECTION -----------------------
    @property
    def current_page_num(self):
        return self.active_page

    def on_page_select(self, event):
        if not self.page_listbox.curselection():
            return
        index = self.page_listbox.curselection()[0]
        self.active_page = index + 1
        self.show_page(self.active_page)

    def show_page(self, page_num):
        if not self.images:
            return
        self.active_page = page_num
        self.current_page_label.config(text=f"Current Page: {page_num:02}")
        self.original_page = self.images[page_num - 1]
        self.update_idletasks()

        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()

        # Auto-zoom so that the page is as large as possible without cutting off
        self.zoom = min(canvas_width / self.original_page.width,
                        canvas_height / self.original_page.height)

        self.redraw_page()
        self.update_bbox_listbox()

    def redraw_page(self):
        if not self.original_page:
            return
        new_width = int(self.original_page.width * self.zoom)
        new_height = int(self.original_page.height * self.zoom)

        try:
            resample_method = Image.Resampling.LANCZOS
        except AttributeError:
            # Pillow < 9
            resample_method = Image.ANTIALIAS

        self.scaled_page = self.original_page.resize((new_width, new_height), resample_method)
        self.current_page_tk = ImageTk.PhotoImage(self.scaled_page)
        self.canvas.delete("all")
        self.canvas_image_id = self.canvas.create_image(0, 0, anchor="nw", image=self.current_page_tk)
        self.canvas.config(scrollregion=(0, 0, new_width, new_height))

        # Draw bounding boxes
        for bbox in self.annotations.get(self.current_page_num, []):
            color = self.get_color_for_label(bbox.label)
            bbox.rect_id = None
            bbox.text_id = None
            bbox.anchor_id = None
            bbox.draw(self.zoom, color)

    def update_bbox_listbox(self):
        self.bbox_listbox.delete(0, tk.END)
        for i, bbox in enumerate(self.annotations.get(self.current_page_num, [])):
            entry = f"{i+1:02}. {bbox.label}"
            self.bbox_listbox.insert(tk.END, entry)
        self.update_bbox_listbox_selection()

    def update_bbox_listbox_selection(self):
        self.bbox_listbox.selection_clear(0, tk.END)
        if self.selected_bbox:
            try:
                index = self.annotations[self.current_page_num].index(self.selected_bbox)
                self.bbox_listbox.selection_set(index)
            except ValueError:
                pass

    # ----------------------- BBOX SELECTION -----------------------
    def deselect_all(self):
        for bbox in self.annotations.get(self.current_page_num, []):
            bbox.selected = False
            bbox.draw(self.zoom, self.get_color_for_label(bbox.label))
        self.selected_bbox = None
        self.update_bbox_listbox_selection()
        self.update_coord_label(0, 0)

    def get_color_for_label(self, label):
        if label not in self.label_color_map:
            c = COLOR_CYCLE[self.color_index % len(COLOR_CYCLE)]
            self.color_index += 1
            self.label_color_map[label] = c
        return self.label_color_map[label]

    def on_bbox_list_select(self, event):
        if not self.bbox_listbox.curselection():
            return
        index = self.bbox_listbox.curselection()[0]
        bbox = self.annotations[self.current_page_num][index]
        self.deselect_all()
        bbox.selected = True
        self.selected_bbox = bbox
        bbox.draw(self.zoom, self.get_color_for_label(bbox.label))
        self.center_bbox(bbox)
        self.update_bbox_listbox_selection()
        self.update_coord_label(0, 0)

    def center_bbox(self, bbox):
        s_coords = [coord * self.zoom for coord in bbox.orig_coords]
        center_x = (s_coords[0] + s_coords[2]) / 2
        center_y = (s_coords[1] + s_coords[3]) / 2
        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()
        total_width = self.scaled_page.width
        total_height = self.scaled_page.height
        x_fraction = max(0, min(1, (center_x - canvas_width/2) / total_width))
        y_fraction = max(0, min(1, (center_y - canvas_height/2) / total_height))
        self.canvas.xview_moveto(x_fraction)
        self.canvas.yview_moveto(y_fraction)

    # ----------------------- BBOX EDIT/DELETE -----------------------
    def open_edit_bbox_dialog(self, bbox):
        current_page = self.current_page_num
        dialog = EditBBoxDialog(
            self,
            "Edit Bounding Box",
            bbox,
            self.properties_dict,
            on_properties_changed=self.build_property_frames
        )
        self.mark_unsaved()
        self.page_listbox.selection_clear(0, tk.END)
        self.page_listbox.selection_set(current_page-1)
        self.redraw_page()
        self.update_bbox_listbox()

    def edit_bbox_dialog(self, event):
        # Triggered by double-clicking in the bbox listbox.
        selection = self.bbox_listbox.curselection()
        if not selection:
            return
        index = selection[0]
        bbox = self.annotations[self.current_page_num][index]
        self.open_edit_bbox_dialog(bbox)


    def on_bbox_list_right_click(self, event):
        index = self.bbox_listbox.nearest(event.y)
        if index < 0 or index >= len(self.annotations[self.current_page_num]):
            return
        confirm = messagebox.askyesno("Delete Bounding Box", "Are you sure you want to delete this box?")
        if confirm:
            bbox = self.annotations[self.current_page_num][index]
            if bbox.rect_id:
                self.canvas.delete(bbox.rect_id)
            if bbox.text_id:
                self.canvas.delete(bbox.text_id)
            if bbox.anchor_id:
                self.canvas.delete(bbox.anchor_id)
            del self.annotations[self.current_page_num][index]
            self.mark_unsaved()
            self.update_bbox_listbox()
            self.redraw_page()

    # ----------------------- CANVAS EVENTS -----------------------
    def on_canvas_right_click(self, event):
        # Triggered by right-clicking a bounding box on the canvas.
        x = self.canvas.canvasx(event.x)
        y = self.canvas.canvasy(event.y)
        for bbox in reversed(self.annotations.get(self.current_page_num, [])):
            if bbox.is_inside(x, y, self.zoom):
                # Deselect anything currently selected
                self.deselect_all()

                # Select this bbox
                bbox.selected = True
                self.selected_bbox = bbox
                bbox.draw(self.zoom, self.get_color_for_label(bbox.label))
                self.update_bbox_listbox_selection()
                self.open_edit_bbox_dialog(bbox)
                return

    def on_canvas_mouse_down(self, event):
        x = self.canvas.canvasx(event.x)
        y = self.canvas.canvasy(event.y)
        # Check for anchor
        if self.selected_bbox and self.selected_bbox.is_on_anchor(x, y, self.zoom):
            self.resizing = True
            self.resize_start_x = x
            self.resize_start_y = y
            self.resize_initial_br = (self.selected_bbox.orig_coords[2], self.selected_bbox.orig_coords[3])
            return

        # Check for existing bounding boxes (select for moving)
        for bbox in reversed(self.annotations.get(self.current_page_num, [])):
            if bbox.is_inside(x, y, self.zoom):
                self.deselect_all()
                bbox.selected = True
                self.selected_bbox = bbox
                self.moving = True
                self.move_start_x = x
                self.move_start_y = y
                bbox.draw(self.zoom, self.get_color_for_label(bbox.label))
                self.update_bbox_listbox_selection()
                self.update_coord_label(x, y)
                return

        # Otherwise, start a new bounding box
        self.deselect_all()
        self.drawing = True
        self.start_x = x
        self.start_y = y
        self.temp_rect = self.canvas.create_rectangle(
            self.start_x, self.start_y, self.start_x, self.start_y,
            outline="black", width=2
        )
        self.update_coord_label(x, y)

    def on_canvas_mouse_move(self, event):
        x = self.canvas.canvasx(event.x)
        y = self.canvas.canvasy(event.y)
        if self.resizing and self.selected_bbox:
            new_br_x = self.resize_initial_br[0] + (x - self.resize_start_x) / self.zoom
            new_br_y = self.resize_initial_br[1] + (y - self.resize_start_y) / self.zoom
            if new_br_x - self.selected_bbox.orig_coords[0] < MIN_DRAG_THRESHOLD:
                new_br_x = self.selected_bbox.orig_coords[0] + MIN_DRAG_THRESHOLD
            if new_br_y - self.selected_bbox.orig_coords[1] < MIN_DRAG_THRESHOLD:
                new_br_y = self.selected_bbox.orig_coords[1] + MIN_DRAG_THRESHOLD
            self.selected_bbox.orig_coords[2] = new_br_x
            self.selected_bbox.orig_coords[3] = new_br_y
            self.selected_bbox.draw(self.zoom, self.get_color_for_label(self.selected_bbox.label))

        elif self.moving and self.selected_bbox:
            dx = x - self.move_start_x
            dy = y - self.move_start_y
            self.selected_bbox.move(dx, dy, self.zoom)
            self.selected_bbox.draw(self.zoom, self.get_color_for_label(self.selected_bbox.label))
            self.move_start_x = x
            self.move_start_y = y

        elif self.drawing and self.temp_rect:
            self.canvas.coords(self.temp_rect, self.start_x, self.start_y, x, y)

        self.update_coord_label(x, y)

    def on_canvas_mouse_up(self, event):
        if self.resizing:
            self.resizing = False
            self.mark_unsaved()
            self.update_bbox_listbox_selection()
        elif self.moving:
            self.moving = False
            self.mark_unsaved()
            self.update_bbox_listbox_selection()
        elif self.drawing:
            self.drawing = False
            end_x = self.canvas.canvasx(event.x)
            end_y = self.canvas.canvasy(event.y)
            if (abs(end_x - self.start_x) < MIN_DRAG_THRESHOLD or 
                abs(end_y - self.start_y) < MIN_DRAG_THRESHOLD):
                self.canvas.delete(self.temp_rect)
                self.temp_rect = None
                self.deselect_all()
                return

            orig_start_x = self.start_x / self.zoom
            orig_start_y = self.start_y / self.zoom
            orig_end_x = end_x / self.zoom
            orig_end_y = end_y / self.zoom
            x1, y1 = min(orig_start_x, orig_end_x), min(orig_start_y, orig_end_y)
            x2, y2 = max(orig_start_x, orig_end_x), max(orig_start_y, orig_end_y)
            self.canvas.delete(self.temp_rect)
            self.temp_rect = None

            new_bbox = BoundingBox(self.canvas, x1, y1, x2, y2, label=DEFAULT_LABEL)
            self.annotations[self.current_page_num].append(new_bbox)
            new_bbox.draw(self.zoom, self.get_color_for_label(new_bbox.label))
            self.mark_unsaved()
            self.update_bbox_listbox()

    def on_canvas_motion(self, event):
        x = self.canvas.canvasx(event.x)
        y = self.canvas.canvasy(event.y)
        if not (self.drawing or self.moving or self.resizing or self.selected_bbox):
            self.update_coord_label(x, y)

    def update_coord_label(self, canvas_x, canvas_y):
        if self.selected_bbox and (self.moving or self.resizing):
            bx1, by1, bx2, by2 = self.selected_bbox.orig_coords
            text = f"Start: {bx1:.1f}, {by1:.1f}\nEnd: {bx2:.1f}, {by2:.1f}"
            self.coord_label.config(text=text, fg="black")
        elif self.drawing and self.temp_rect:
            orig_x = canvas_x / self.zoom
            orig_y = canvas_y / self.zoom
            text = (f"Drawing from: {self.start_x/self.zoom:.1f}, {self.start_y/self.zoom:.1f}\n"
                    f"Current: {orig_x:.1f}, {orig_y:.1f}")
            self.coord_label.config(text=text, fg="dimgray")
        else:
            orig_x = canvas_x / self.zoom
            orig_y = canvas_y / self.zoom
            text = f"Pos.: {orig_x:.1f}, {orig_y:.1f}"
            self.coord_label.config(text=text, fg="dimgray")

    def on_mousewheel(self, event):
        if hasattr(event, 'delta') and event.delta:
            factor = 1.1 if event.delta > 0 else 0.9
        elif event.num == 4:
            factor = 1.1
        elif event.num == 5:
            factor = 0.9
        else:
            factor = 1.0
        self.zoom *= factor
        self.redraw_page()


if __name__ == "__main__":
    app = PDFAnnotationTool()
    app.mainloop()

# TODO: Export to zip file with option for changed image ratios (e.g. square) in various formats, esp. JSON