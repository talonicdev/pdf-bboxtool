# Basic Bounding Box Annotation Tool for PDFs

This is a very basic GUI-only tool for limited bounding box annotation tasks on PDFs where the large suites might feel like overkill.
The tool will open PDFs directly and allows for users to draw, move, resize and label bounding boxes on all pages before exporting them to JSON.

## Features

- **PDF Conversion**: Converts each page of a PDF into an image using a user-specified DPI.
- **Interactive Annotation**:
  - **Drawing**: Click and drag on the image to create bounding boxes.
  - **Moving**: Select a bounding box by clicking inside it, then drag to reposition.
  - **Resizing**: Resize bounding boxes using a visible anchor at the bottom-right corner. (The cursor will change to indicate resize mode.)
  - **Editing**: Double-click on a bounding box in the sidebar or right-click on it in the canvas to edit its label and type.
  - **Deletion**: Right-click on a bounding box in the sidebar to delete it.
- **Annotation Management**:
  - A sidebar displays the list of pages and a list of bounding boxes for the current page.
  - Live coordinate display shows the cursor position (or, when drawing, both the start and current positions). When a bounding box is selected, the coordinates are shown as static values.
- **File Handling**:
  - Save and load progress at any time.
  - Export individual pages or all of them zipped as PNG files.
  - Export annotations in standard `{"bboxes": [[x1, y1, x2, y2]], "labels":["foo"]}` format.

## Installation

### Prerequisites

- **Python 3.7+** is required.
- **Poppler** is needed by `pdf2image` to convert PDF pages to images.

### Installing Poppler

- **Linux**:  
  Install poppler using your package manager. For example, on Debian/Ubuntu, run:
  
  ```bash
  sudo apt-get install poppler-utils
  ```

- **macOS**:  
  Install poppler using Homebrew:
  
  ```bash
  brew install poppler
  ```

- **Windows**:  
  Download the latest poppler package from [this repository](https://github.com/oschwartz10612/poppler-windows). Extract it and add the `bin/` folder to your system PATH.

### Python Dependencies

Install the required Python packages using pip:

```bash
pip install -r requirements.txt
```

## Usage

1. **Open a PDF**:  
   Use the "File" menu to open a PDF file. Each page will be converted into an image and listed in the sidebar.

2. **Set DPI**:  
   Enter your desired DPI in the DPI field and click the "Set" button. (This will reload the PDF pages at the new DPI and adjust any existing bounding box coordinates accordingly.)

3. **Annotate**:  
   - **Drawing**: Click and drag on the image to create a bounding box.
   - **Moving**: Click inside an existing bounding box to select it and then drag to reposition.
   - **Resizing**: Hover over the bottom-right anchor of a selected bounding box (the cursor will change to indicate resize mode) and drag to resize.
   - **Editing**: Double-click a bounding box in the sidebar or right-click on a bounding box in the canvas to open the dialog for editing its label and type.
   - **Deletion**: Right-click on a bounding box in the sidebar to delete it.

4. **Coordinate Display**:  
   The sidebar displays the cursor’s current position as “Pos.: x, y”. When drawing, it shows both the start and current positions. If a bounding box is selected, it shows that box’s static coordinates.

5. **Save/Load Annotations**:  
   Save your annotations to a JSON file. The JSON file stores the PDF filename, date, MD5 checksum, DPI, page dimensions, and the bounding boxes. When loading, if the annotations’ DPI differs from the current setting or if the PDF checksum does not match, the tool will prompt you for how to proceed.

## Workflow

- **Start**: Launch the application and open a PDF file.
- **Set DPI**: Adjust the DPI if necessary using the provided input and "Set" button.
- **Annotate**: Create, move, resize, and label bounding boxes on each page as needed.
- **Manage Annotations**: Use the sidebar to view, select, edit, or delete bounding boxes.
- **Save/Load**: Save your work to a JSON file and load it later when needed.

*(Additional licensing and collaboration details will be added later.)*
