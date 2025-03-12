#!/usr/bin/env python3
import tkinter as tk
from tkinter import filedialog, simpledialog, messagebox
from tkinter import ttk
from PIL import Image, ImageTk
from pdf2image import convert_from_path
import json, datetime, os, hashlib, io, zipfile

MIN_DRAG_THRESHOLD = 5    # pixels; below this, a click is treated as a simple deselection
ANCHOR_SIZE = 8           # size (in pixels) of the resize anchor

# --- Tooltip class ---
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
        self.id = self.widget.after(500, self.showtip)
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
        label = tk.Label(tw, text=self.text, justify=tk.LEFT,
                         background="#ffffe0", relief=tk.SOLID, borderwidth=1,
                         font=("tahoma", "8", "normal"))
        label.pack(ipadx=1)
    def hidetip(self):
        tw = self.tipwindow
        self.tipwindow = None
        if tw:
            tw.destroy()

# --- Helper for MD5 checksum ---
def md5_checksum(file_path):
    hash_md5 = hashlib.md5()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    except Exception:
        return None

# --- LabelTypeDialog ---
class LabelTypeDialog(simpledialog.Dialog):
    def __init__(self, parent, title, initial_label="", initial_type="", types_list=None):
        self.initial_label = initial_label if initial_label else "No Label"
        self.initial_type = initial_type if initial_type else "No Type"
        self.types_list = types_list if types_list is not None else []
        self.result = None
        super().__init__(parent, title=title)
    def body(self, master):
        tk.Label(master, text="Label:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        self.label_entry = tk.Entry(master)
        self.label_entry.grid(row=0, column=1, padx=5, pady=5)
        self.label_entry.insert(0, self.initial_label)
        tk.Label(master, text="Type:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        self.type_combo = ttk.Combobox(master, values=self.types_list, state="normal")
        self.type_combo.grid(row=1, column=1, padx=5, pady=5)
        self.type_combo.set(self.initial_type)
        return self.label_entry
    def apply(self):
        self.result = (self.label_entry.get(), self.type_combo.get())

# --- BoundingBox class ---
class BoundingBox:
    def __init__(self, canvas, x1, y1, x2, y2, label="No Label", type_str="No Type", color="red", name=""):
        self.canvas = canvas
        self.orig_coords = [x1, y1, x2, y2]  # in original image coordinates
        self.label = label
        self.type_str = type_str
        self.color = color
        self.name = name
        self.rect_id = None
        self.text_id = None
        self.anchor_id = None
        self.selected = False
    def draw(self, scale):
        s_coords = [coord * scale for coord in self.orig_coords]
        width = 4 if self.selected else 2
        if self.rect_id is None:
            self.rect_id = self.canvas.create_rectangle(
                *s_coords,
                outline=self.color,
                width=width,
                fill=self.color,
                stipple="gray50",
                tags=("bbox_rect",)
            )
        else:
            self.canvas.coords(self.rect_id, *s_coords)
            self.canvas.itemconfig(self.rect_id, width=width, fill=self.color, stipple="gray50", outline=self.color)
        # Draw label text.
        text_x = (s_coords[0] + s_coords[2]) / 2
        text_y = s_coords[1] - 10
        display_text = f"{self.name}: {self.label} ({self.type_str})"
        if self.text_id is None:
            self.text_id = self.canvas.create_text(text_x, text_y, text=display_text, fill="black")
        else:
            self.canvas.coords(self.text_id, text_x, text_y)
            self.canvas.itemconfig(self.text_id, text=display_text)
        # Draw resize anchor if selected.
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
                self.canvas.coords(self.anchor_id,
                                   anchor_x - ANCHOR_SIZE, anchor_y - ANCHOR_SIZE,
                                   anchor_x, anchor_y)
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
    def update_label_type(self, label, type_str):
        self.label = label
        self.type_str = type_str

# --- Main Application ---
class PDFAnnotationTool(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Basic Bounding Box Annotation Tool")
        self.geometry("1200x800")
        self.unsaved_changes = False
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self.pdf_file = None
        self.images = []          # List of PIL images (pages) at original resolution.
        self.original_page = None
        self.scaled_page = None
        self.current_page_tk = None
        self.annotations = {}     # { page_number: [BoundingBox, ...] }
        self.color_cycle = ["red", "blue", "green", "orange", "purple", "yellow", "grey", "cyan", "pink", "light sea green", "IndianRed1", "dark khaki"]
        self.current_color_index = 0
        self.current_dpi = None
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
        self.drawing_color = None
        self.resizing = False
        self.resize_start_x = None
        self.resize_start_y = None
        self.resize_initial_br = None

        self.last_save_path = None

        # New property for bounding box types.
        self.types = ["No Type"]

        self.create_widgets()

    def update_title(self):
        base = "Basic Bounding Box Annotation Tool"
        self.title(base + (" *" if self.unsaved_changes else ""))
        
    def update_page_list(self):
        self.page_listbox.delete(0, tk.END)
        num_pages = len(self.images)
        for i in range(num_pages):
            count = len(self.annotations.get(i+1, []))
            self.page_listbox.insert(tk.END, f" Page {i+1:02} ({count})")

    def update_types_listbox(self):
        self.type_listbox.delete(0, tk.END)
        for t in self.types:
            self.type_listbox.insert(tk.END, t)

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

    def create_widgets(self):
        # Menubar with File and Export menus.
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

        # Main paned window: sidebar and main display.
        self.paned = tk.PanedWindow(self, orient=tk.HORIZONTAL)
        self.paned.pack(fill=tk.BOTH, expand=True)

        # Sidebar frame.
        self.sidebar = tk.Frame(self.paned, width=300)
        self.paned.add(self.sidebar)

        # Sidebar top: DPI selection.
        self.sidebar_top = tk.Frame(self.sidebar)
        self.sidebar_top.pack(fill=tk.X)
        dpi_frame = tk.Frame(self.sidebar_top)
        dpi_frame.pack(pady=5)
        tk.Label(dpi_frame, text="DPI:").pack(side=tk.LEFT)
        self.dpi_var = tk.IntVar(value=300)
        self.dpi_entry = tk.Entry(dpi_frame, textvariable=self.dpi_var, width=5)
        self.dpi_entry.pack(side=tk.LEFT)
        tk.Button(dpi_frame, text="Set", command=self.on_dpi_change).pack(side=tk.LEFT)
        CreateToolTip(self.dpi_entry, "Enter desired DPI and click Set.")

        # New vertical paned window for three lists: Pages, Types, and Bounding Boxes.
        self.sidebar_paned = tk.PanedWindow(self.sidebar, orient=tk.VERTICAL)
        self.sidebar_paned.pack(fill=tk.BOTH, expand=True)

        # Pages Frame.
        self.pages_frame = tk.Frame(self.sidebar_paned)
        self.sidebar_paned.add(self.pages_frame)
        tk.Label(self.pages_frame, text="Pages:").pack(fill=tk.X)
        self.page_listbox = tk.Listbox(self.pages_frame)
        self.page_listbox.pack(fill=tk.BOTH, expand=True)
        self.page_listbox.bind("<<ListboxSelect>>", self.on_page_select)
        CreateToolTip(self.page_listbox, "Select a page to view.")
        # New "Current Page" label below the pages list
        self.current_page_label = tk.Label(self.pages_frame, text="Current Page: --", fg="dimgray")
        self.current_page_label.pack(fill=tk.X, pady=(2, 0))
        # Add a horizontal separator
        ttk.Separator(self.pages_frame, orient="horizontal").pack(fill="x", pady=(2, 5))

        # Types Frame.
        self.types_frame = tk.Frame(self.sidebar_paned)
        self.sidebar_paned.add(self.types_frame)
        tk.Label(self.types_frame, text="Types:").pack(fill=tk.X)
        self.type_listbox = tk.Listbox(self.types_frame)
        self.type_listbox.pack(fill=tk.BOTH, expand=True)
        type_btn_frame = tk.Frame(self.types_frame)
        type_btn_frame.pack(fill=tk.X)
        tk.Button(type_btn_frame, text="Add", command=self.add_type).pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Button(type_btn_frame, text="Edit", command=self.edit_type).pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Button(type_btn_frame, text="Del", command=self.delete_type).pack(side=tk.LEFT, fill=tk.X, expand=True)
        CreateToolTip(self.type_listbox, "Select a type for bounding boxes.")
        self.update_types_listbox()

        # Bounding Boxes Frame.
        self.bbox_frame = tk.Frame(self.sidebar_paned)
        self.sidebar_paned.add(self.bbox_frame)
        tk.Label(self.bbox_frame, text="Bounding Boxes:").pack(fill=tk.X)
        self.bbox_listbox = tk.Listbox(self.bbox_frame)
        self.bbox_listbox.pack(fill=tk.BOTH, expand=True)
        self.bbox_listbox.bind("<<ListboxSelect>>", self.on_bbox_list_select)
        self.bbox_listbox.bind("<Double-Button-1>", self.edit_bbox)
        self.bbox_listbox.bind("<Button-3>", self.on_bbox_list_right_click)
        CreateToolTip(self.bbox_listbox, "Select a bounding box. Double-click to edit, right-click to delete.")

        # Coordinates display.
        self.coord_label = tk.Label(self.sidebar, text="", fg="dimgray", justify=tk.LEFT, height=3)
        self.coord_label.pack(fill=tk.X)
        CreateToolTip(self.coord_label, "Displays cursor position or bounding box coordinates.")

        # Main display frame.
        self.main_frame = tk.Frame(self.paned)
        self.paned.add(self.main_frame)
        self.canvas_frame = tk.Frame(self.main_frame)
        self.canvas_frame.pack(fill=tk.BOTH, expand=True)
        self.canvas = tk.Canvas(self.canvas_frame, bg="gray")
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.vbar = tk.Scrollbar(self.canvas_frame, orient=tk.VERTICAL, command=self.canvas.yview)
        self.vbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.hbar = tk.Scrollbar(self.main_frame, orient=tk.HORIZONTAL, command=self.canvas.xview)
        self.hbar.pack(side=tk.BOTTOM, fill=tk.X)
        self.canvas.configure(yscrollcommand=self.vbar.set, xscrollcommand=self.hbar.set, cursor="crosshair")
        self.canvas.bind("<ButtonPress-1>", self.on_canvas_mouse_down)
        self.canvas.bind("<B1-Motion>", self.on_canvas_mouse_move)
        self.canvas.bind("<ButtonRelease-1>", self.on_canvas_mouse_up)
        self.canvas.bind("<MouseWheel>", self.on_mousewheel)
        self.canvas.bind("<Button-4>", self.on_mousewheel)
        self.canvas.bind("<Button-5>", self.on_mousewheel)
        self.canvas.bind("<Button-3>", self.on_canvas_right_click)
        self.canvas.bind("<Motion>", self.on_canvas_motion)
        self.canvas.tag_bind("bbox_rect", "<Enter>", lambda e: self.canvas.config(cursor="fleur"))
        self.canvas.tag_bind("bbox_rect", "<Leave>", lambda e: self.canvas.config(cursor="crosshair"))
        self.canvas.tag_bind("anchor", "<Enter>", lambda e: self.canvas.config(cursor="bottom_right_corner"))
        self.canvas.tag_bind("anchor", "<Leave>", lambda e: self.canvas.config(cursor="crosshair"))

    def add_type(self):
        new_type = simpledialog.askstring("Add Type", "Enter new type:")
        if new_type and new_type not in self.types:
            self.types.append(new_type)
            self.update_types_listbox()

    def edit_type(self):
        if not self.type_listbox.curselection():
            return
        index = self.type_listbox.curselection()[0]
        current_type = self.types[index]
        new_type = simpledialog.askstring("Edit Type", "Edit type:", initialvalue=current_type)
        if new_type:
            self.types[index] = new_type
            self.update_types_listbox()

    def delete_type(self):
        if not self.type_listbox.curselection():
            return
        index = self.type_listbox.curselection()[0]
        confirm = messagebox.askyesno("Delete Type", f"Delete type '{self.types[index]}'?")
        if confirm:
            del self.types[index]
            self.update_types_listbox()

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

    def open_pdf(self):
        file_path = filedialog.askopenfilename(filetypes=[("PDF Files", "*.pdf")])
        if not file_path:
            return
        self.pdf_file = file_path
        dpi = self.dpi_var.get()
        self.current_dpi = dpi
        self.current_checksum = md5_checksum(self.pdf_file)
        try:
            self.images = convert_from_path(self.pdf_file, dpi=dpi)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to convert PDF: {e}")
            return
        self.annotations = {}
        self.page_listbox.delete(0, tk.END)
        for i, img in enumerate(self.images):
            self.page_listbox.insert(tk.END, f" Page {i+1}")
            self.annotations[i+1] = []
        self.update_page_list()
        self.page_listbox.selection_set(0)
        self.last_save_path = None
        self.mark_saved()
        self.show_page(1)

    def load_annotations(self):
        file_path = filedialog.askopenfilename(filetypes=[("JSON Files", "*.json")])
        if not file_path:
            return
        try:
            with open(file_path, "r") as f:
                data = json.load(f)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load JSON: {e}")
            return
        new_pdf = data.get("filename")
        saved_checksum = data.get("checksum")
        current_checksum = md5_checksum(self.pdf_file) if self.pdf_file else None
        load_associated = False
        if self.pdf_file and (os.path.abspath(self.pdf_file) != os.path.abspath(new_pdf) or current_checksum != saved_checksum):
            resp = messagebox.askyesnocancel("PDF Mismatch",
                "The annotations file is for a different PDF.\n"
                "Yes: Load the PDF associated with the annotations.\n"
                "No: Apply annotations on top of the current PDF.\n"
                "Cancel: Abort loading.")
            if resp is None:
                return
            if resp:
                load_associated = True
        if load_associated:
            self.pdf_file = new_pdf
            self.current_checksum = md5_checksum(self.pdf_file)
            dpi = data.get("dpi", self.dpi_var.get())
            self.dpi_var.set(dpi)
            self.current_dpi = dpi
            try:
                self.images = convert_from_path(self.pdf_file, dpi=dpi)
            except Exception as e:
                messagebox.showerror("Error", f"Failed to convert PDF: {e}")
                return
        else:
            if not self.pdf_file:
                self.pdf_file = new_pdf
                self.current_checksum = md5_checksum(self.pdf_file)
                dpi = data.get("dpi", self.dpi_var.get())
                self.dpi_var.set(dpi)
                self.current_dpi = dpi
                try:
                    self.images = convert_from_path(self.pdf_file, dpi=dpi)
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to convert PDF: {e}")
                    return
            else:
                saved_dpi = data.get("dpi", self.dpi_var.get())
                if saved_dpi != self.current_dpi:
                    self.dpi_var.set(saved_dpi)
                    self.current_dpi = saved_dpi
                    try:
                        self.images = convert_from_path(self.pdf_file, dpi=saved_dpi)
                    except Exception as e:
                        messagebox.showerror("Error", f"Failed to convert PDF: {e}")
                        return
        # Load types if present.
        types_loaded = data.get("types")
        if types_loaded is not None:
            self.types = types_loaded
        else:
            self.types = ["No Type"]
        self.update_types_listbox()
        self.annotations = {}
        self.page_listbox.delete(0, tk.END)
        for i, img in enumerate(self.images):
            self.page_listbox.insert(tk.END, f" Page {i+1}")
            self.annotations[i+1] = []
        for page_data in data.get("pages", []):
            page_num = page_data.get("page")
            for bbox_data in page_data.get("bboxes", []):
                label = bbox_data.get("label", "No Label")
                type_str = bbox_data.get("type", "No Type")
                coords = bbox_data.get("bbox", [0, 0, 0, 0])
                color = self.color_cycle[self.current_color_index % len(self.color_cycle)]
                self.current_color_index += 1
                name = f" {len(self.annotations[page_num]) + 1:02}"
                bbox = BoundingBox(self.canvas, *coords, label=label, type_str=type_str, color=color, name=name)
                self.annotations[page_num].append(bbox)
        self.update_page_list()
        self.page_listbox.selection_set(0)
        self.last_save_path = file_path
        self.mark_saved()
        self.show_page(1)

    def _save_annotations_to(self, save_path):
        data = {
            "filename": self.pdf_file,
            "date": datetime.datetime.now().isoformat(),
            "checksum": md5_checksum(self.pdf_file),
            "dpi": self.current_dpi,
            "types": self.types,
            "pages": []
        }
        for page_num, boxes in self.annotations.items():
            img = self.images[page_num - 1]
            dimensions = {"width": img.width, "height": img.height}
            page_data = {"page": page_num, "dimensions": dimensions, "bboxes": []}
            for box in boxes:
                coords = [round(coord, 2) for coord in box.orig_coords]
                page_data["bboxes"].append({"label": box.label, "type": box.type_str, "bbox": coords})
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
        save_path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON Files", "*.json")])
        if not save_path:
            return
        self._save_annotations_to(save_path)

    def export_image(self):
        if not self.original_page:
            messagebox.showerror("Error", "No page loaded.")
            return
        save_path = filedialog.asksaveasfilename(title="Save image as..", filetypes=[("PNG files", "*.png")], defaultextension=".png")
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
        save_path = filedialog.asksaveasfilename(title="Save zip file as..", filetypes=[("ZIP file", ".zip")],
                                                 initialfile=f"{os.path.splitext(os.path.basename(self.pdf_file))[0]}.images.zip")
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
        save_path = filedialog.asksaveasfilename(title="Export bboxes as JSON", filetypes=[("JSON Files", "*.json")], defaultextension=".json")
        if not save_path:
            return
        try:
            with open(save_path, "w") as f:
                json.dump(data, f, indent=2)
            messagebox.showinfo("Export", "Bounding boxes exported successfully.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to export bounding boxes: {e}")

    def on_page_select(self, event):
        if not self.page_listbox.curselection():
            return
        index = self.page_listbox.curselection()[0]
        page_num = index + 1
        self.show_page(page_num)

    def show_page(self, page_num):
        self.current_page_num = page_num
        self.original_page = self.images[page_num - 1]
        self.update_idletasks()
        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()
        if self.original_page.width > canvas_width or self.original_page.height > canvas_height:
            self.zoom = min(canvas_width / self.original_page.width, canvas_height / self.original_page.height)
        else:
            self.zoom = 1.0
        self.redraw_page()
        self.update_bbox_listbox()
        self.update_page_list()
        # Update the current page label below the pages list.
        self.current_page_label.config(text=f"Current Page: {page_num:02}")

    def redraw_page(self):
        new_width = int(self.original_page.width * self.zoom)
        new_height = int(self.original_page.height * self.zoom)
        try:
            resample_method = Image.Resampling.LANCZOS
        except AttributeError:
            resample_method = Image.ANTIALIAS
        self.scaled_page = self.original_page.resize((new_width, new_height), resample_method)
        self.current_page_tk = ImageTk.PhotoImage(self.scaled_page)
        self.canvas.delete("all")
        self.canvas_image_id = self.canvas.create_image(0, 0, anchor="nw", image=self.current_page_tk)
        self.canvas.config(scrollregion=(0, 0, new_width, new_height))
        for bbox in self.annotations.get(self.current_page_num, []):
            bbox.rect_id = None
            bbox.text_id = None
            bbox.anchor_id = None
            bbox.draw(self.zoom)

    def update_bbox_listbox(self):
        self.bbox_listbox.delete(0, tk.END)
        for bbox in self.annotations.get(self.current_page_num, []):
            entry = f"{bbox.name}: {bbox.label} ({bbox.type_str})"
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

    def deselect_all(self):
        for bbox in self.annotations.get(self.current_page_num, []):
            bbox.selected = False
            bbox.draw(self.zoom)
        self.selected_bbox = None
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

    def update_coord_label(self, canvas_x, canvas_y):
        if self.selected_bbox:
            bx1, by1, bx2, by2 = self.selected_bbox.orig_coords
            text = f"Start: {bx1:.1f}, {by1:.1f}\nPos.: {bx2:.1f}, {by2:.1f}"
            self.coord_label.config(text=text, fg="black")
        elif self.drawing:
            orig_x = canvas_x / self.zoom
            orig_y = canvas_y / self.zoom
            text = f"Start: {self.start_x/self.zoom:.1f}, {self.start_y/self.zoom:.1f}\nPos.: {orig_x:.1f}, {orig_y:.1f}"
            self.coord_label.config(text=text, fg="dimgray")
        else:
            orig_x = canvas_x / self.zoom
            orig_y = canvas_y / self.zoom
            text = f"Pos.: {orig_x:.1f}, {orig_y:.1f}"
            self.coord_label.config(text=text, fg="dimgray")

    def on_canvas_motion(self, event):
        x = self.canvas.canvasx(event.x)
        y = self.canvas.canvasy(event.y)
        if not (self.drawing or self.moving or self.resizing or self.selected_bbox):
            self.update_coord_label(x, y)

    def on_bbox_list_select(self, event):
        if not self.bbox_listbox.curselection():
            return
        index = self.bbox_listbox.curselection()[0]
        bbox = self.annotations[self.current_page_num][index]
        self.deselect_all()
        bbox.selected = True
        self.selected_bbox = bbox
        bbox.draw(self.zoom)
        self.center_bbox(bbox)
        self.update_bbox_listbox_selection()
        self.update_coord_label(0, 0)

    def on_bbox_list_right_click(self, event):
        index = self.bbox_listbox.nearest(event.y)
        if index < 0 or index >= len(self.annotations[self.current_page_num]):
            return
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
        self.update_page_list()
        self.redraw_page()

    def edit_bbox(self, event):
        selection = self.bbox_listbox.curselection()
        if not selection:
            return
        index = selection[0]
        bbox = self.annotations[self.current_page_num][index]
        dialog = LabelTypeDialog(self, "Edit Bounding Box", bbox.label, bbox.type_str, types_list=self.types)
        if dialog.result:
            new_label, new_type = dialog.result
            if new_type not in self.types:
                self.types.append(new_type)
                self.update_types_listbox()
            bbox.update_label_type(new_label, new_type)
            bbox.draw(self.zoom)
            self.mark_unsaved()
            self.update_bbox_listbox()

    def on_canvas_right_click(self, event):
        x = self.canvas.canvasx(event.x)
        y = self.canvas.canvasy(event.y)
        for bbox in reversed(self.annotations.get(self.current_page_num, [])):
            if bbox.is_inside(x, y, self.zoom):
                dialog = LabelTypeDialog(self, "Edit Bounding Box", bbox.label, bbox.type_str, types_list=self.types)
                if dialog.result:
                    new_label, new_type = dialog.result
                    if new_type not in self.types:
                        self.types.append(new_type)
                        self.update_types_listbox()
                    bbox.update_label_type(new_label, new_type)
                    bbox.draw(self.zoom)
                    self.mark_unsaved()
                    self.update_bbox_listbox()
                return

    def on_canvas_mouse_down(self, event):
        x = self.canvas.canvasx(event.x)
        y = self.canvas.canvasy(event.y)
        if self.selected_bbox and self.selected_bbox.is_on_anchor(x, y, self.zoom):
            self.resizing = True
            self.resize_start_x = x
            self.resize_start_y = y
            self.resize_initial_br = (self.selected_bbox.orig_coords[2], self.selected_bbox.orig_coords[3])
            return
        for bbox in reversed(self.annotations.get(self.current_page_num, [])):
            if bbox.is_inside(x, y, self.zoom):
                self.deselect_all()
                bbox.selected = True
                self.selected_bbox = bbox
                self.moving = True
                self.move_start_x = x
                self.move_start_y = y
                bbox.draw(self.zoom)
                self.update_bbox_listbox_selection()
                self.update_coord_label(x, y)
                return
        self.deselect_all()
        self.drawing = True
        self.start_x = x
        self.start_y = y
        self.drawing_color = self.color_cycle[self.current_color_index % len(self.color_cycle)]
        self.current_color_index += 1
        self.temp_rect = self.canvas.create_rectangle(
            self.start_x, self.start_y, self.start_x, self.start_y,
            outline=self.drawing_color, width=2
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
            self.selected_bbox.draw(self.zoom)
        elif self.moving and self.selected_bbox:
            dx = x - self.move_start_x
            dy = y - self.move_start_y
            self.selected_bbox.move(dx, dy, self.zoom)
            self.selected_bbox.draw(self.zoom)
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
            if abs(end_x - self.start_x) < MIN_DRAG_THRESHOLD or abs(end_y - self.start_y) < MIN_DRAG_THRESHOLD:
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
            color = self.drawing_color
            self.drawing_color = None
            name = f" {len(self.annotations[self.current_page_num]) + 1:02}"
            new_bbox = BoundingBox(self.canvas, x1, y1, x2, y2,
                                   label="No Label",
                                   type_str="No Type",
                                   color=color, name=name)
            self.annotations[self.current_page_num].append(new_bbox)
            new_bbox.draw(self.zoom)
            self.mark_unsaved()
            self.update_bbox_listbox()
            self.update_page_list()

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
    menubar = tk.Menu(app)
    filemenu = tk.Menu(app, tearoff=0)
    filemenu.add_command(label="Open PDF", command=app.open_pdf)
    filemenu.add_command(label="Load Annotations", command=app.load_annotations)
    filemenu.add_separator()
    filemenu.add_command(label="Save", command=app.save)
    filemenu.add_command(label="Save as..", command=app.save_as)
    menubar.add_cascade(label="File", menu=filemenu)
    exportmenu = tk.Menu(app, tearoff=0)
    exportmenu.add_command(label="Export image", command=app.export_image)
    exportmenu.add_command(label="Export all images", command=app.export_all_images)
    exportmenu.add_command(label="Export bboxes", command=app.export_bboxes)
    menubar.add_cascade(label="Export", menu=exportmenu)
    app.config(menu=menubar)
    app.mainloop()
