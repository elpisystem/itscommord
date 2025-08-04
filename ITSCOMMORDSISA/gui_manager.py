import tkinter as tk
from tkinter import messagebox, PhotoImage
import os
import sys

# Costanti per la GUI (potrebbero essere spostate in constants.py)
BG_COLOR = "#1e1e1e"
FG_COLOR = "#ffffff"
BTN_COLOR = "#66CC66"
HIGHLIGHT = "#555555"

# Globale per conservare riferimento all'immagine del logo, altrimenti non viene mostrata
logo_img_tk_ref = None
# Globale per tenere traccia dello stato dell'importazione (per animazione e chiusura)
# Questo dovrà essere sincronizzato o gestito tramite callback dal thread principale
terminate_import_flag_gui = False


def resource_path_gui(relative_path):
    """ Ottiene il percorso assoluto alla risorsa, funziona per dev e per PyInstaller """
    try:
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


class AppGUI:
    def __init__(self, root_tk, app_config, pv_info_text="PV: N/A", start_import_callback=None, on_close_callback=None):
        self.root = root_tk
        self.config = app_config # Still useful for other configs if any
        self.pv_info_text = pv_info_text # New parameter for PV info
        self.start_import_callback = start_import_callback
        self.on_close_callback = on_close_callback

        self.terminate_import = False # Flag specifico della GUI, potrebbe essere collegato a un flag globale

        self._setup_window()
        self._create_widgets()
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing_window_internal)

    def _setup_window(self):
        self.root.title("Importazione File su STORE")
        self.root.configure(bg=BG_COLOR)
        self.root.resizable(False, False)

        window_width = 480
        window_height = 450 # Potrebbe necessitare aggiustamenti con layout verticale animazione

        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        position_top = int(screen_height / 2 - window_height / 2)
        position_left = int(screen_width / 2 - window_width / 2)
        self.root.geometry(f"{window_width}x{window_height}+{position_left}+{position_top}")
        self.root.attributes('-topmost', True)

        try:
            icon_path_png = resource_path_gui("logo.png")
            if os.path.exists(icon_path_png):
                global logo_img_tk_ref # Usa il globale per conservare il riferimento
                logo_img_tk_ref = PhotoImage(file=icon_path_png) # Salva in una variabile che non viene garbage collected
                self.root.iconphoto(True, logo_img_tk_ref)
            else:
                print(f"GUI: Icon file logo.png not found at {icon_path_png}")
        except Exception as e:
            print(f"GUI: Errore caricamento icona logo.png: {e}")

    def _create_widgets(self):
        # Etichetta Info PV (utilizza self.pv_info_text passato da main)
        # self.config.get("GUI_INFO_TEXT", ...) è ora un fallback se pv_info_text non fosse fornito (improbabile con il default)
        effective_info_text = self.pv_info_text
        if not effective_info_text: # Fallback nel caso pv_info_text sia None o vuoto per qualche motivo
            effective_info_text = self.config.get("GUI_INFO_TEXT", "PV: Dati non disponibili")

        self.info_label = tk.Label(
            self.root, text=effective_info_text, font=("Arial", 11),
            bg="#3a3a3a", fg="#ffffff", anchor="center", padx=10, pady=4
        )
        self.info_label.pack(fill='x', pady=(5, 0))

        # Listbox per i log
        self.listbox_frame = tk.Frame(self.root, bg=BG_COLOR)
        self.listbox_frame.pack(pady=10, fill=tk.BOTH, expand=True)
        self.scrollbar = tk.Scrollbar(self.listbox_frame)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.file_listbox = tk.Listbox(
            self.listbox_frame, width=55, height=10, bg=BG_COLOR, fg=FG_COLOR,
            highlightbackground=HIGHLIGHT, selectbackground="#444",
            yscrollcommand=self.scrollbar.set
        )
        self.file_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scrollbar.config(command=self.file_listbox.yview)

        # Etichetta Progresso
        self.progress_label = tk.Label(self.root, text="", font=("Arial", 10), bg=BG_COLOR, fg=FG_COLOR)
        self.progress_label.pack(pady=(0,5))

        # Frame Contenitore Animazione (puntini e logo)
        self.animation_container_frame = tk.Frame(self.root, bg=BG_COLOR)
        # Questo frame verrà mostrato/nascosto da show/hide_animation_elements

        # Frame Puntini (dentro animation_container_frame)
        self.dots_frame = tk.Frame(self.animation_container_frame, bg=BG_COLOR)
        self.dots_labels = [
            tk.Label(self.dots_frame, text="●", font=("Arial", 18), fg=FG_COLOR, bg=BG_COLOR, height=1),
            tk.Label(self.dots_frame, text="●", font=("Arial", 18), fg=FG_COLOR, bg=BG_COLOR, height=1),
            tk.Label(self.dots_frame, text="●", font=("Arial", 18), fg=FG_COLOR, bg=BG_COLOR, height=1),
        ]
        for lbl in self.dots_labels:
            lbl.pack(side=tk.TOP, pady=0) # Layout verticale pallini

        # Label Logo (dentro animation_container_frame)
        self.logo_label_widget = tk.Label(self.animation_container_frame, bg=BG_COLOR)
        self.logo_animation_img_ref = None # Riferimento per l'immagine del logo nell'animazione

        # Bottone Download
        self.btn_download = tk.Button(
            self.root, text="Scarica Tutti i File", font=("Arial", 12),
            command=self._on_download_click, bg=BTN_COLOR, fg=FG_COLOR,
            activebackground="#444", activeforeground=FG_COLOR
        )
        self.btn_download.pack(pady=20)

    def _on_download_click(self):
        if self.start_import_callback:
            # Pulisci la listbox e il progress label prima di avviare
            self.file_listbox.delete(0, tk.END)
            self.progress_label.config(text="")
            self.start_import_callback() # Chiama la funzione nel main thread che avvia il worker

    def _on_closing_window_internal(self):
        if self.on_close_callback:
            self.on_close_callback() # Chiama la logica di chiusura definita nel main
        else:
            self.root.destroy() # Comportamento di default se nessun callback specificato

    # --- Metodi Pubblici per controllare la GUI dall'esterno ---
    def safe_insert_listbox(self, text, is_error=False):
        if not self.root.winfo_exists(): return
        def _insert():
            self.file_listbox.insert(tk.END, text)
            if is_error:
                self.file_listbox.itemconfig(tk.END, {'fg': 'red'})
            self.file_listbox.yview_moveto(1)
        self.root.after(0, _insert)

    def safe_set_progress(self, text):
        if not self.root.winfo_exists(): return
        self.root.after(0, lambda: self.progress_label.config(text=text))

    def _mostra_logo_animazione(self):
        try:
            logo_path_gui = resource_path_gui("logo.png")
            if os.path.exists(logo_path_gui):
                img = PhotoImage(file=logo_path_gui)
                self.logo_animation_img_ref = img.subsample(5) # Conserva riferimento
                self.logo_label_widget.config(image=self.logo_animation_img_ref)
            else:
                print(f"GUI: Logo per animazione non trovato: {logo_path_gui}")
        except Exception as e:
            print(f"GUI: Errore caricamento logo per animazione: {e}")

    def _animate_dots_gui(self, counter=0):
        # Usa il flag terminate_import di questa istanza GUI
        # che dovrebbe essere impostato dal thread principale tramite un metodo
        if self.terminate_import or not self.animation_container_frame.winfo_ismapped():
            return
        active = counter % 3
        for i, lbl in enumerate(self.dots_labels):
            lbl.config(fg=FG_COLOR if i == active else "#555555")
        self.root.after(300, lambda: self._animate_dots_gui(counter + 1))

    def show_animation_elements(self):
        if not self.root.winfo_exists(): return
        def _show():
            self.btn_download.pack_forget()
            self.dots_frame.pack(side=tk.TOP, pady=(0, 2))
            self.logo_label_widget.pack(side=tk.TOP, pady=(2, 0))
            self.animation_container_frame.pack(pady=5)
            self._mostra_logo_animazione()
            self.terminate_import = False # Resetta flag per nuova animazione
            # Schedule the animation to start slightly after the pack operation
            self.root.after(50, self._animate_dots_gui) # Small delay, e.g., 50ms
        self.root.after(0, _show)

    def hide_animation_elements(self):
        if not self.root.winfo_exists(): return
        def _hide():
            self.animation_container_frame.pack_forget()
            self.btn_download.pack(pady=10) # Ripristina il bottone
        self.root.after(0, _hide)

    def show_message(self, type, title, message):
        if not self.root.winfo_exists(): return
        def _show():
            if type == "info": messagebox.showinfo(title, message)
            elif type == "warning": messagebox.showwarning(title, message)
            elif type == "error": messagebox.showerror(title, message)
        self.root.after(0, _show)

    def ask_yes_no(self, title, message):
        # Questo è bloccante, quindi non può essere messo in root.after se il chiamante si aspetta una risposta immediata.
        # Dovrebbe essere chiamato dal thread principale della GUI.
        if not self.root.winfo_exists(): return False # Default se la finestra non esiste
        return messagebox.askyesno(title, message)

    def destroy_window(self):
        if self.root.winfo_exists():
            self.root.destroy()

# Esempio di utilizzo (per testare solo la GUI)
if __name__ == '__main__':
    test_config = {
        "LOCAL_IMPORT_DIR": "C:/test_import",
        "GUI_INFO_TEXT": "Test PDV: 00000"
    }

    root_tk = tk.Tk()
    app_gui = AppGUI(root_tk, test_config)

    def dummy_start_import():
        print("Dummy Start Import Chiamato")
        app_gui.show_animation_elements()
        app_gui.safe_set_progress("Simulazione importazione...")
        for i in range(5):
            app_gui.safe_insert_listbox(f"File {i+1} processato.")
            root_tk.update() # Forzato per vedere gli aggiornamenti nel test
            # time.sleep(0.5) # Rimosso time.sleep per evitare di bloccare il test della GUI

        # Simula la fine dell'importazione dopo un po'
        def end_sim():
            app_gui.safe_set_progress("Simulazione completata.")
            app_gui.hide_animation_elements()
            app_gui.show_message("info", "Completato", "Simulazione di importazione terminata.")

        # Simula il flag di terminazione (per testare l'animazione che si ferma)
        # app_gui.terminate_import = True # Testa se l'animazione si ferma

        root_tk.after(3000, end_sim) # Simula la fine dopo 3 secondi

    def dummy_on_close():
        print("Dummy On Close Chiamato")
        if app_gui.ask_yes_no("Uscire?", "Sei sicuro di voler uscire dalla simulazione?"):
            app_gui.destroy_window()

    app_gui.start_import_callback = dummy_start_import
    app_gui.on_close_callback = dummy_on_close

    root_tk.mainloop()
