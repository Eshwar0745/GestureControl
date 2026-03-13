import customtkinter as ctk
from PIL import Image
import threading
import sys
import os

from gesture_engine import GestureEngine

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Gesture Control Dashboard")
        self.geometry("1100x650")
        self.minsize(900, 500)
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        # Basic grid layout: 1 row, 2 columns
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)  # Camera view takes remaining space
        self.grid_columnconfigure(1, weight=0)  # Sidebar has fixed width

        # --- Sidebar ---
        self.sidebar_frame = ctk.CTkFrame(self, width=280, corner_radius=0)
        self.sidebar_frame.grid(row=0, column=1, sticky="nsew")
        self.sidebar_frame.grid_propagate(False) # Prevent sidebar from shrinking below requested width
        self.sidebar_frame.grid_rowconfigure(6, weight=1)

        self.logo_label = ctk.CTkLabel(self.sidebar_frame, text="Gesture Control", font=ctk.CTkFont(size=20, weight="bold"))
        self.logo_label.grid(row=0, column=0, padx=20, pady=(20, 10))

        # Status
        self.status_label = ctk.CTkLabel(self.sidebar_frame, text="Status: Starting...", text_color="orange")
        self.status_label.grid(row=1, column=0, padx=20, pady=5)

        # Volume
        self.vol_label = ctk.CTkLabel(self.sidebar_frame, text="Volume: --%")
        self.vol_label.grid(row=2, column=0, padx=20, pady=(15, 0), sticky="w")
        self.vol_progressbar = ctk.CTkProgressBar(self.sidebar_frame)
        self.vol_progressbar.grid(row=3, column=0, padx=20, pady=(5, 15), sticky="ew")
        self.vol_progressbar.set(0)

        # Brightness
        self.bright_label = ctk.CTkLabel(self.sidebar_frame, text="Brightness: --%")
        self.bright_label.grid(row=4, column=0, padx=20, pady=0, sticky="w")
        self.bright_progressbar = ctk.CTkProgressBar(self.sidebar_frame)
        self.bright_progressbar.grid(row=5, column=0, padx=20, pady=(5, 15), sticky="ew")
        self.bright_progressbar.set(0)

        # Current Gestures
        self.gestures_textbox = ctk.CTkTextbox(self.sidebar_frame, height=100)
        self.gestures_textbox.grid(row=6, column=0, padx=20, pady=10, sticky="nsew")
        self.gestures_textbox.insert("0.0", "Active Gestures:\nNone")
        self.gestures_textbox.configure(state="disabled")

        # Controls
        self.help_btn = ctk.CTkButton(self.sidebar_frame, text="How to Use", command=self.show_instructions, fg_color="gray", hover_color="darkgray")
        self.help_btn.grid(row=7, column=0, padx=20, pady=(10, 0))

        self.toggle_cam_btn = ctk.CTkButton(self.sidebar_frame, text="Stop Camera", command=self.toggle_camera)
        self.toggle_cam_btn.grid(row=8, column=0, padx=20, pady=(10, 0))

        self.exit_btn = ctk.CTkButton(self.sidebar_frame, text="Exit", command=self.on_closing, fg_color="red", hover_color="darkred")
        self.exit_btn.grid(row=9, column=0, padx=20, pady=(10, 20))

        # --- Main View (Camera) ---
        self.cam_frame = ctk.CTkFrame(self)
        self.cam_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        self.cam_frame.grid_rowconfigure(0, weight=1)
        self.cam_frame.grid_columnconfigure(0, weight=1)

        self.video_label = ctk.CTkLabel(self.cam_frame, text="Waking up camera...")
        self.video_label.grid(row=0, column=0, sticky="nsew")

        # Start backend engine
        self.engine = GestureEngine()
        
        # Start camera in a background thread to prevent UI freezing during init
        threading.Thread(target=self._start_engine, daemon=True).start()

        # Update loop
        self.update_gui()

    def _start_engine(self):
        self.engine.start(0)
        self.status_label.configure(text="Status: Active", text_color="green")

    def show_instructions(self):
        help_window = ctk.CTkToplevel(self)
        help_window.title("How to Use Gestures")
        help_window.geometry("500x420")
        help_window.attributes("-topmost", True)
        
        # Adding instructions text
        title_lbl = ctk.CTkLabel(help_window, text="Gesture Instructions", font=ctk.CTkFont(size=20, weight="bold"))
        title_lbl.pack(pady=15)
        
        instructions = (
            "🤚 Right Hand (Audio & Media Controls):\n"
            "  • Pinch (Thumb + Index): Adjust Volume Up/Down\n"
            "  • Fist: Mute PC Volume\n"
            "  • Open Palm (all 5 fingers): Unmute Volume\n"
            "  • Thumb Up (other fingers closed): Play Media\n"
            "  • Thumb Down (other fingers closed): Pause Media\n\n"
            "🤚 Left Hand (Display Controls):\n"
            "  • Pinch (Thumb + Index): Adjust Screen Brightness\n\n"
            "💡 Pro Tips:\n"
            "  • Ensure your hand is clearly visible in the camera.\n"
            "  • The left-hand brightness feature calibrates itself; just open and close your hand once to secure the full brightness range!."
        )
        
        text_box = ctk.CTkTextbox(help_window, wrap="word", font=ctk.CTkFont(size=14))
        text_box.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        text_box.insert("0.0", instructions)
        text_box.configure(state="disabled")

    def toggle_camera(self):
        if self.engine.running:
            self.engine.stop()
            self.toggle_cam_btn.configure(text="Start Camera")
            self.status_label.configure(text="Status: Stopped", text_color="red")
            self.video_label.configure(image="", text="Camera stopped")
        else:
            self.status_label.configure(text="Status: Starting...", text_color="orange")
            threading.Thread(target=self._start_engine, daemon=True).start()
            self.toggle_cam_btn.configure(text="Stop Camera")

    def update_gui(self):
        if self.engine.running:
            state = self.engine.get_state()
            
            # Update Frame
            if state["frame"] is not None:
                # We dynamically resize image to fit the frame keeping aspect ratio
                frame_w = self.cam_frame.winfo_width()
                frame_h = self.cam_frame.winfo_height()
                
                # To prevent division by zero before window fully loads
                if frame_w > 100 and frame_h > 100:
                    img = Image.fromarray(state["frame"])
                    # Use CustomTkinter Image
                    ctk_image = ctk.CTkImage(light_image=img, dark_image=img, size=(frame_w - 20, frame_h - 20))
                    self.video_label.configure(image=ctk_image, text="")
            
            # Update Dashboard Status
            vol = state["volume"]
            mute = state["muted"]
            bright = state["brightness"]
            
            self.vol_label.configure(text=f"Volume: {'Muted' if mute else str(vol) + '%'}")
            self.vol_progressbar.set(vol / 100.0)
            
            self.bright_label.configure(text=f"Brightness: {bright}%")
            self.bright_progressbar.set(bright / 100.0)
            
            # Update Gestures
            self.gestures_textbox.configure(state="normal")
            self.gestures_textbox.delete("0.0", "end")
            gestures = state["gestures"]
            text = "Active Gestures:\n\n" + ("\n".join(gestures) if gestures else "None")
            self.gestures_textbox.insert("0.0", text)
            self.gestures_textbox.configure(state="disabled")

        # Schedule next update
        self.after(30, self.update_gui)

    def on_closing(self):
        self.engine.stop()
        self.destroy()
        sys.exit(0)

if __name__ == "__main__":
    app = App()
    app.mainloop()
