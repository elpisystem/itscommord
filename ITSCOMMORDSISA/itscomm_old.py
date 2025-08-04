import os
import sys
import threading
import tkinter as tk
from tkinter import messagebox
from tkinter import PhotoImage # Assicurati che sia importato
from ftplib import FTP, error_perm
import time
import xml.etree.ElementTree as ET
import shutil # Aggiunto per la copia dei file

# === CONFIGURAZIONE DA XML ===
def load_ftp_config(xml_file_path="ftp_itscommconfig.xml"):
    try:
        tree = ET.parse(xml_file_path)
        root = tree.getroot()

        ftp_node = root.find("ftp")
        local_node = root.find("local")

        config = {
            "FTP_HOST": ftp_node.find("host").text.strip(),
            "FTP_USER": ftp_node.find("user").text.strip(),
            "FTP_PASS": ftp_node.find("password").text.strip(),
            "FTP_BASE_DIR": ftp_node.find("base_dir").text.strip(),
            "LOCAL_IMPORT_DIR": local_node.find("import_dir").text.strip(),
            "ORDINE_DIR": local_node.find("ordine_dir").text.strip() if local_node.find("ordine_dir") is not None else None
        }
        if not config["ORDINE_DIR"]:
            print("Avviso: Il tag <ordine_dir> non è configurato o è vuoto nel file XML. La copia secondaria non verrà eseguita.")
        return config
    except Exception as e:
        messagebox.showerror("Errore Configurazione", f"Impossibile caricare ftp_itscommconfig.xml: {e}")
        sys.exit(1)

# Carica parametri
ftp_config = load_ftp_config()
FTP_HOST = ftp_config["FTP_HOST"]
FTP_USER = ftp_config["FTP_USER"]
FTP_PASS = ftp_config["FTP_PASS"]
FTP_BASE_DIR = ftp_config["FTP_BASE_DIR"]
LOCAL_IMPORT_DIR = ftp_config["LOCAL_IMPORT_DIR"]
ORDINE_DIR = ftp_config.get("ORDINE_DIR") # Usa .get() per sicurezza
FTP_TARGET_DIR = "/importati"

# === STATO ===
terminate_import = False # Usato globalmente
import_thread = None
errors_occurred = []

# === FUNZIONI DI UTILITÀ ===
def resource_path(relative_path): # Definito globalmente
    try:
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# === GUI Setup (tema scuro) ===
BG_COLOR = "#1e1e1e"
FG_COLOR = "#ffffff"
BTN_COLOR = "#66CC66"
HIGHLIGHT = "#555555"

root = tk.Tk()
root.title("Importazione File su STORE")

# Imposta l'icona per la finestra e la taskbar
try:
    icon_path_png = resource_path("logo.png")
    if os.path.exists(icon_path_png):
        icon = PhotoImage(file=icon_path_png)
        root.iconphoto(True, icon)
    else:
        print(f"Icon file logo.png not found at {icon_path_png}")
except Exception as e:
    print(f"Errore caricamento icona logo.png: {e}")

root.configure(bg=BG_COLOR)
root.resizable(False, False)
window_width = 480
window_height = 450 # Altezza originale, potrebbe necessitare aggiustamento per layout verticale

screen_width = root.winfo_screenwidth()
screen_height = root.winfo_screenheight()
position_top = int(screen_height / 2 - window_height / 2)
position_left = int(screen_width / 2 - window_width / 2)
root.geometry(f"{window_width}x{window_height}+{position_left}+{position_top}")
root.attributes('-topmost', True)

info_label = tk.Label(
    root,
    text="PDV: 00103  ROSITANO", # Testo statico come richiesto
    font=("Arial", 11),
    bg="#3a3a3a",
    fg="#ffffff",
    anchor="center",
    padx=10,
    pady=4
)
info_label.pack(fill='x', pady=(5, 0))

listbox_frame = tk.Frame(root, bg=BG_COLOR)
listbox_frame.pack(pady=10, fill=tk.BOTH, expand=True)

scrollbar = tk.Scrollbar(listbox_frame)
scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

file_listbox = tk.Listbox(listbox_frame, width=55, height=10,
                          bg=BG_COLOR, fg=FG_COLOR, highlightbackground=HIGHLIGHT,
                          selectbackground="#444", yscrollcommand=scrollbar.set)
file_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
scrollbar.config(command=file_listbox.yview)

progress_label = tk.Label(root, text="", font=("Arial", 10), bg=BG_COLOR, fg=FG_COLOR)
progress_label.pack(pady=(0,5))


# === Elementi per animazione e logo (gestiti centralmente) ===
animation_container_frame = tk.Frame(root, bg=BG_COLOR)

dots_frame = tk.Frame(animation_container_frame, bg=BG_COLOR)
dots_labels = [
    tk.Label(dots_frame, text="●", font=("Arial", 18), fg=FG_COLOR, bg=BG_COLOR, height=1),
    tk.Label(dots_frame, text="●", font=("Arial", 18), fg=FG_COLOR, bg=BG_COLOR, height=1),
    tk.Label(dots_frame, text="●", font=("Arial", 18), fg=FG_COLOR, bg=BG_COLOR, height=1),
]
for lbl in dots_labels:
    lbl.pack(side=tk.TOP, pady=0) # MODIFICA: side=tk.TOP per layout verticale dei pallini, pady ridotto

logo_img_tk = None
logo_label_widget = tk.Label(animation_container_frame, bg=BG_COLOR)


def mostra_logo_gui():
    global logo_img_tk
    try:
        logo_path_gui = resource_path("logo.png")
        if os.path.exists(logo_path_gui):
            img = PhotoImage(file=logo_path_gui)
            logo_img_tk = img.subsample(5)
            logo_label_widget.config(image=logo_img_tk)
        else:
            print(f"Logo per GUI non trovato: {logo_path_gui}")
    except Exception as e:
        print(f"Errore caricamento logo per GUI: {e}")

def animate_dots_gui(counter=0):
    if terminate_import or not animation_container_frame.winfo_ismapped():
        return
    active = counter % 3
    for i, lbl in enumerate(dots_labels):
        lbl.config(fg=FG_COLOR if i == active else "#555555")
    root.after(300, lambda: animate_dots_gui(counter + 1))

def show_animation_elements():
    # MODIFICA: Layout verticale per dots_frame e logo_label_widget
    dots_frame.pack(side=tk.TOP, pady=(0, 2)) # pady per separare un po' dal logo
    logo_label_widget.pack(side=tk.TOP, pady=(2, 0)) # pady per separare un po' dai pallini
    animation_container_frame.pack(pady=5)

    mostra_logo_gui()
    animate_dots_gui()

def hide_animation_elements():
    animation_container_frame.pack_forget()
    # Non è necessario fare pack_forget dei figli se il container è nascosto
    # dots_frame.pack_forget()
    # logo_label_widget.pack_forget()


# === FUNZIONI DI CALLBACK PER LA GUI ===
def safe_insert_listbox(text, is_error=False):
    if not root.winfo_exists(): return
    def _insert():
        file_listbox.insert(tk.END, text)
        if is_error:
            file_listbox.itemconfig(tk.END, {'fg': 'red'})
        file_listbox.yview_moveto(1)
    root.after(0, _insert)

def safe_set_progress(text):
    if not root.winfo_exists(): return
    root.after(0, lambda: progress_label.config(text=text))

# === LOGICA DI IMPORTAZIONE (THREAD) ===
def check_local_dir():
    try:
        if not os.path.exists(LOCAL_IMPORT_DIR):
            os.makedirs(LOCAL_IMPORT_DIR, exist_ok=True)
            safe_insert_listbox(f"Directory locale creata: {LOCAL_IMPORT_DIR}")
        test_file = os.path.join(LOCAL_IMPORT_DIR, ".tmp_write_test")
        with open(test_file, "w") as f: f.write("test")
        os.remove(test_file)
        return True
    except Exception as e:
        messagebox.showerror("Errore Directory Locale",
                             f"Impossibile creare o scrivere su '{LOCAL_IMPORT_DIR}':\n{e}")
        safe_set_progress("Errore directory locale.")
        return False

def run_import_thread_task():
    global terminate_import, errors_occurred
    errors_occurred = []

    if not check_local_dir():
        root.after(0, lambda: (
            btn_download.pack(pady=10), # Ripristina bottone
            hide_animation_elements()
        ))
        return

    root.after(0, lambda: (
        btn_download.pack_forget(),
        show_animation_elements()
    ))

    safe_set_progress("Connessione all'FTP...")
    ftp = None
    try:
        ftp = FTP(FTP_HOST, timeout=30)
        ftp.login(FTP_USER, FTP_PASS)
        if FTP_BASE_DIR and FTP_BASE_DIR != "/":
             ftp.cwd(FTP_BASE_DIR)
        safe_insert_listbox(f"Connesso a FTP: {FTP_HOST}")
    except Exception as e:
        safe_set_progress("Errore di connessione FTP.")
        errors_occurred.append(f"Connessione FTP fallita: {e}")
        root.after(0, lambda: messagebox.showerror("Errore FTP", f"Connessione fallita:\n{e}"))
        # finally gestirà il ripristino della GUI
        return

    try:
        current_dir = ftp.pwd()
        try:
            ftp.cwd(FTP_TARGET_DIR)
            safe_insert_listbox(f"Directory FTP '{FTP_TARGET_DIR}' già esistente.")
        except error_perm:
            try:
                ftp.mkd(FTP_TARGET_DIR)
                safe_insert_listbox(f"Directory FTP '{FTP_TARGET_DIR}' creata.")
            except Exception as e_mkd:
                msg = f"Errore creazione dir '{FTP_TARGET_DIR}' su FTP: {e_mkd}"
                safe_insert_listbox(msg, is_error=True); errors_occurred.append(msg)
        finally:
            ftp.cwd(current_dir)

        safe_set_progress("Ricerca file su FTP...")
        remote_files = ftp.nlst()
        if not remote_files:
            safe_insert_listbox("Nessun file trovato nella directory FTP di base.")

        files_processed_count = 0
        for fname in remote_files:
            if terminate_import:
                safe_insert_listbox("Importazione interrotta dall'utente.")
                break
            if "/" in fname or fname == "." or fname == "..": continue

            local_name = f"divulgaz{fname}"
            local_path = os.path.join(LOCAL_IMPORT_DIR, local_name)

            try:
                safe_set_progress(f"Scaricamento: {fname}...")
                with open(local_path, "wb") as f:
                    ftp.retrbinary(f"RETR {fname}", f.write)
                safe_insert_listbox(f"Scaricato: {fname} → {local_name}")
                files_processed_count +=1
            except Exception as e_retr:
                msg = f"Errore scaricamento {fname}: {e_retr}"
                safe_insert_listbox(msg, is_error=True); errors_occurred.append(msg)
                if os.path.exists(local_path): os.remove(local_path)
                continue

            try:
                target_ftp_path = f"{FTP_TARGET_DIR.rstrip('/')}/{fname}"
                ftp.rename(fname, target_ftp_path)
                safe_insert_listbox(f"Spostato su FTP: {fname} → {FTP_TARGET_DIR}/")
            except Exception as e_mv:
                msg = f"Errore spostamento FTP {fname} → {target_ftp_path}: {e_mv}"
                safe_insert_listbox(msg, is_error=True); errors_occurred.append(msg)

            # === COPIA NELLA ORDINE_DIR ===
            if ORDINE_DIR: # Procede solo se ORDINE_DIR è configurato
                try:
                    # Tentativo di creare la directory ORDINE_DIR.
                    # exist_ok=True significa che non solleverà un errore se la directory esiste già.
                    # Solleverà un errore se il percorso esiste ma non è una directory, o per problemi di permessi.
                    try:
                        os.makedirs(ORDINE_DIR, exist_ok=True)
                        # Il messaggio "Directory creata" potrebbe essere mostrato solo la prima volta se necessario,
                        # ma per ora lo omettiamo per ridurre il verboso se la dir esiste sempre.
                    except Exception as e_mkdir_ordine:
                        # Se makedirs fallisce per un motivo serio (es. permessi, percorso non valido, il percorso è un file)
                        msg = f"Errore critico con directory di destinazione {ORDINE_DIR}: {e_mkdir_ordine}"
                        safe_insert_listbox(msg, is_error=True)
                        errors_occurred.append(msg)
                        continue # Passa al prossimo file FTP, non tentare la copia in ORDINE_DIR per questo file

                    # local_path è il file già rinominato in LOCAL_IMPORT_DIR
                    dest_path_ordine_dir = os.path.join(ORDINE_DIR, local_name)

                    shutil.copy2(local_path, dest_path_ordine_dir)
                    safe_insert_listbox(f"Copiato: {local_name} → {ORDINE_DIR}")

                except Exception as e_copy_ordine:
                    # Questa eccezione cattura errori da shutil.copy2 o altri problemi imprevisti nel blocco try principale
                    msg = f"Errore durante la copia di {local_name} a {ORDINE_DIR}: {e_copy_ordine}"
                    safe_insert_listbox(msg, is_error=True)
                    errors_occurred.append(msg)
                    # L'errore è stato loggato, il ciclo continua con il prossimo file FTP
            # === FINE COPIA NELLA ORDINE_DIR ===

    except Exception as e_task_main:
        safe_set_progress("Errore durante l'elaborazione dei file.")
        error_msg = f"Si è verificato un errore durante l'elaborazione FTP:\n{e_task_main}"
        errors_occurred.append(error_msg)
        import traceback
        traceback.print_exc()
        root.after(0, lambda: messagebox.showerror("Errore Elaborazione FTP", error_msg))

    finally:
        if ftp:
            try: ftp.quit()
            except Exception as e_quit: print(f"Errore durante ftp.quit(): {e_quit}")

        if terminate_import:
            safe_set_progress("Importazione interrotta.")
        elif not errors_occurred:
            safe_set_progress("Scaricamento completato.")
            root.after(0, lambda: messagebox.showinfo("Completato", f"{files_processed_count} file scaricati e spostati con successo."))
        else:
            safe_set_progress(f"Completato con {len(errors_occurred)} errori.")
            error_summary = "\n".join(errors_occurred[:5])
            if len(errors_occurred) > 5: error_summary += f"\n...e altri {len(errors_occurred) - 5} errori."
            root.after(0, lambda: messagebox.showwarning("Completato con Errori",
                                                         f"Operazione completata con {len(errors_occurred)} errori:\n\n{error_summary}"))

        terminate_import = False
        if root.winfo_exists():
            root.after(0, lambda: (
                hide_animation_elements(),
                btn_download.pack(pady=10)
            ))

# === GESTORI EVENTI ===
def start_import_action():
    global import_thread, terminate_import
    terminate_import = False
    file_listbox.delete(0, tk.END)
    progress_label.config(text="")

    if import_thread and import_thread.is_alive():
        messagebox.showwarning("Attenzione", "Importazione già in corso.")
        return

    import_thread = threading.Thread(target=run_import_thread_task, daemon=True)
    import_thread.start()

btn_download = tk.Button(root, text="Scarica Tutti i File", font=("Arial", 12), command=start_import_action,
                         bg=BTN_COLOR, fg=FG_COLOR, activebackground="#444", activeforeground=FG_COLOR)
btn_download.pack(pady=20)

def on_closing_window():
    global terminate_import, import_thread
    if import_thread and import_thread.is_alive():
        if messagebox.askyesno("Conferma Uscita", "Importazione in corso. Interrompere e uscire?"):
            terminate_import = True
            root.destroy()
    else:
        root.destroy()

root.protocol("WM_DELETE_WINDOW", on_closing_window)
root.mainloop()
