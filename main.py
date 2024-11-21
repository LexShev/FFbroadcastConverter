import tkinter as tk
import tkinter.ttk as ttk
import os
import sys
import sqlite3
import threading
import subprocess
import time
import re
import pywinstyles
import cv2
import render
from tkinterdnd2 import TkinterDnD, DND_FILES
from tkinter import filedialog
from PIL import Image, ImageTk
from media_info import insert_media_info

db_path = 'media_info.db'
conn = sqlite3.connect('media_info.db')
cursor = conn.cursor()
process_states = {}
file_list_states = {}

# Функция для получения пути к ресурсам
def resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        # Путь, где PyInstaller хранит временные файлы
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

logo = resource_path("logo.png")
style_tcl = resource_path("style.tcl")
forest_dark_path = resource_path("forest-dark")

class App(TkinterDnD.Tk):
    def __init__(self):
        super().__init__()
        self.title("FFmpeg Converter")
        self.conn, self.cursor = self.create_db_connection()
        self.setup_style()

        # Иконка приложения
        icon_image = tk.PhotoImage(file=logo)
        self.wm_iconphoto(True, icon_image)

        # Настройки сетки
        self.columnconfigure(index=0, weight=1)
        self.columnconfigure(index=1, weight=1)
        self.columnconfigure(index=2, weight=1)
        self.rowconfigure(index=0, weight=1)
        self.rowconfigure(index=1, weight=1)
        self.rowconfigure(index=2, weight=1)
        self.rowconfigure(0, weight=0)
        self.rowconfigure(3, weight=0)

        # Создаем Notebook
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(expand=True, fill='both')
        for i in range(1, 6):
            self.create_tab(i)

        # Закрытие программы
        self.protocol("WM_DELETE_WINDOW", self.close_db_connection)

    def setup_style(self):
        style = ttk.Style()
        self.tk.call('source', style_tcl)
        style.theme_use('forest-dark')
        pywinstyles.apply_style(self, 'mica')
        style.configure('Default.TButton')

    def create_db_connection(self):
        conn = sqlite3.connect('media_info.db')
        return conn, conn.cursor()

    def close_db_connection(self):
        self.conn.close()
        self.destroy()

    def load_data(self, file_path, file_list):
        """Загрузка данных из базы данных для файла."""
        with sqlite3.connect('media_info.db') as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, file_name, file_path_to_output, status
                FROM media_info
                WHERE file_path = ?
            ''', (file_path,))
            rows = cursor.fetchall()
            for row in rows:
                if len(row) == 4:
                    id, file_name, file_path_to_output, status = row
                    file_list.insert('', 'end', values=(id, file_name, file_path_to_output, status))
                else:
                    print(f"Unexpected number of columns in row: {row}")

    def load_data_into_treeview(self, file_list, tab_num):
        cursor.execute('SELECT id, file_name, file_path_to_output, status FROM media_info WHERE tab=?', (tab_num,))
        rows = cursor.fetchall()
        file_list.delete(*file_list.get_children())
        for row in rows:
            id, file_name, file_path_to_output, status = row
            file_list.insert('', 'end', values=(id, file_name, file_path_to_output, status))

    def f_inp(self, file_list, tab):
        fd = filedialog.askopenfilenames(title="Выберите медиафайл")
        if not fd:
            return
        progress_window = tk.Toplevel(self)
        progress_window.title("Обработка файлов")
        tk.Label(progress_window, text="Получаем медиа информацию...").pack(pady=10)
        progress_bar = ttk.Progressbar(progress_window, orient="horizontal", length=300, mode="determinate")
        progress_bar.pack(pady=10)
        progress_bar['value'] = 0
        total_files = len(fd)

        def start_processing():
            """Запуск обработки файлов в отдельном потоке."""
            for file_path in fd:
                insert_media_info(db_path, file_path, tab)
                self.load_data(file_path, file_list)
                progress_bar['value'] += 100 / total_files
            progress_window.destroy()

        threading.Thread(target=start_processing).start()

    def f_out(self, file_list):
        selected_items = file_list.selection()
        if not selected_items:
            return

        first_selected_item = selected_items[0]
        output_path = file_list.item(first_selected_item, 'values')[2]
        chosen_path_output = filedialog.askdirectory(title='Укажите каталог для сохранения файлов', initialdir=output_path)

        if not chosen_path_output:
            return

        for selected_item in selected_items:
            id = file_list.item(selected_item, 'values')[0]
            file_name = file_list.item(selected_item, 'values')[1]
            status = 'Ready'
            self.cursor.execute("UPDATE media_info SET file_path_to_output=?, status=? WHERE id=?", 
                                (chosen_path_output, status, id))
            self.conn.commit()
            file_list.item(selected_item, values=(id, file_name, chosen_path_output, 'Ready'))

    def delete_selected_file(self, file_list, audio_frame, sub_frame, widgets_frame, info_text):
        selected_items = file_list.selection()
        for selected_item in selected_items:
            id = file_list.item(selected_item, 'values')[0]

            # Проверка и удаление лог-файла
            self.cursor.execute('''
                SELECT file_name
                FROM media_info
                WHERE id = ?
            ''', (id,))
            file_name = self.cursor.fetchone()[0]
            log_file_name = id + '_' + file_name + '.log'
            log_dir = os.path.join(os.path.dirname(__file__), 'logs')
            log_file_path = os.path.join(log_dir, log_file_name)

            if os.path.exists(log_file_path):
                try:
                    os.remove(log_file_path)
                except Exception as e:
                    print(f"Ошибка при удалении лог-файла {log_file_name}: {e}")

            self.cursor.execute("DELETE FROM audio_tracks WHERE media_info_id=?", (id,))
            self.cursor.execute("DELETE FROM sub_tracks WHERE media_info_id=?", (id,))
            self.cursor.execute("DELETE FROM media_info WHERE id=?", (id,))
            self.conn.commit()

            # Обновление виджетов после удаления
            widgets = widgets_frame.winfo_children()
            lb_in = widgets[2]
            lb_out = widgets[4]
            lb_minus = widgets[6]
            infadespinbox = widgets[8]
            outfadespinbox = widgets[10]
            lb_kor = widgets[12]
            preset_combobox = widgets[14]

            file_list.delete(selected_item)
            lb_in.delete(0, tk.END)
            lb_out.delete(0, tk.END)
            lb_minus.delete(0, tk.END)
            lb_kor.delete(0, tk.END)
            preset_combobox.delete(0, tk.END)
            infadespinbox.delete(0, tk.END)
            outfadespinbox.delete(0, tk.END)

            # Очистка аудио и субтитровых треков
            for widget in audio_frame.winfo_children():
                widget.destroy()
            for widget in sub_frame.winfo_children():
                widget.destroy()

            info_text.config(text="")

    def show_audio_tracks(self, id, audio_frame, file_list):
        try:
            cursor.execute('''
                SELECT selected_audio
                FROM media_info
                WHERE id = ?
            ''', (id,))
            selected_audio = cursor.fetchone()[0]

            cursor.execute('''
                SELECT track_number, codec_name, handler_name, duration, bit_rate, channels, sample_rate, language, title
                FROM audio_tracks
                WHERE media_info_id = ?
            ''', (id,))
            audio_tracks = cursor.fetchall()
            
            for widget in audio_frame.winfo_children():
                widget.destroy()
            
            selected_audio_var = tk.IntVar(value=selected_audio)
            
            if audio_tracks:
                for idx, track in enumerate(audio_tracks, start=1):
                    track_number, codec_name, handler_name, duration, bit_rate, channels, sample_rate, language, title = track
                    radio_button_frame = ttk.Frame(audio_frame)
                    radio_button = ttk.Radiobutton(
                        radio_button_frame, 
                        variable=selected_audio_var, 
                        value=track_number,
                        command=lambda: self.update_selected_audio(selected_audio_var, file_list)
                    )
                    radio_button.pack(side='left')
                    text_frame = ttk.Frame(radio_button_frame)
                    text_frame.pack(side='left', fill='x')
                    
                    title_label = ttk.Label(
                        text_frame,
                        text=f"{title}",
                        font=("Arial", 10, "bold")
                    )
                    title_label.pack(anchor='w')
                    
                    details_label = ttk.Label(
                        text_frame,
                        text=f"{codec_name}, {int(bit_rate / 1000)} Kb/s, {channels} ch, {int(sample_rate / 1000)} kHz, {language}",
                        font=("Arial", 9)
                    )
                    details_label.pack(anchor='w')
                    
                    radio_button_frame.pack(anchor='w', padx=10, pady=5, fill='x')
            else:
                no_tracks_label = ttk.Label(audio_frame, text="Нет доступных аудиодорожек для этого файла")
                no_tracks_label.pack(anchor='w', padx=10, pady=5)
        
        except Exception as e:
            print(f"Ошибка при отображении аудиодорожек: {e}")

    def update_selected_audio(self, selected_audio_var, file_list):
        selected_items = file_list.selection()
        if not selected_items:
            return
        
        selected_audio = selected_audio_var.get()
        for selected_item in selected_items:
            media_info_id = file_list.item(selected_item, 'values')[0]
            
            # Получаем количество аудиодорожек для текущего файла
            cursor.execute('''
                SELECT COUNT(*)
                FROM audio_tracks
                WHERE media_info_id = ?
            ''', (media_info_id,))
            num_audio_tracks = cursor.fetchone()[0]
            
            # Проверяем, что выбранная аудиодорожка не превышает количество доступных аудиодорожек
            if selected_audio > num_audio_tracks:
                print(f"Выбранная аудиодорожка {selected_audio} превышает количество доступных аудиодорожек {num_audio_tracks} для файла с ID {media_info_id}.")
                continue
            
            cursor.execute('''
                UPDATE media_info
                SET selected_audio = ?
                WHERE id = ?
            ''', (selected_audio, media_info_id))
        conn.commit()

    def show_info(self, id, info_text):
        cursor.execute('''
            SELECT duration, bit_rate, fps, video_codec, resolution, color_space
            FROM media_info
            WHERE id = ?
        ''', (id,))
        info = cursor.fetchone()

        if info:
            duration, bit_rate, fps, video_codec, resolution, color_space = info
            info_details = (f"{video_codec} • {duration.split('.')[0]} • "
                            f"{(bit_rate / (1000**2)):.1f} Mb/s • {resolution} • {(fps):.1f} fps • {color_space}")
            info_text.config(text=info_details, font=("Arial", 9))

    def update_selected_sub(self, media_info_id, selected_sub_var, last_selected_sub_var, file_list):
        try:
            selected_items = file_list.selection()
            if not selected_items:
                return
            selected_sub = selected_sub_var.get()
            if selected_sub == last_selected_sub_var.get():
                selected_sub = 0
                selected_sub_var.set(0)

            for selected_item in selected_items:
                media_info_id = file_list.item(selected_item, 'values')[0]

                # Получаем количество субтитров для текущего файла
                cursor.execute('''
                    SELECT COUNT(*)
                    FROM sub_tracks
                    WHERE media_info_id = ?
                ''', (media_info_id,))
                num_sub_tracks = cursor.fetchone()[0]

                if selected_sub > num_sub_tracks:
                    print(f"Выбранная аудиодорожка {selected_sub} превышает количество доступных аудиодорожек {num_sub_tracks} для файла с ID {media_info_id}.")
                    continue

                cursor.execute('''
                    UPDATE media_info
                    SET selected_sub = ?
                    WHERE id = ?
                ''', (selected_sub, media_info_id))
                conn.commit()
                last_selected_sub_var.set(selected_sub)
        except Exception as e:
            print(f"Ошибка при обновлении выбранной дорожки субтитров: {e}")

    def show_sub_tracks(self, id, sub_frame, file_list):
        try:
            # Получаем информацию о выбранной дорожке субтитров
            cursor.execute('''
                SELECT selected_sub, srt, nonsub
                FROM media_info
                WHERE id = ?
            ''', (id,))
            result = cursor.fetchone()
            selected_sub = result[0]
            srt_value = result[1]
            nonsub_value = result[2]

            cursor.execute('''
                SELECT track_number, codec_name, language, title, forc
                FROM sub_tracks
                WHERE media_info_id = ?
            ''', (id,))
            sub_tracks = cursor.fetchall()

            # Очищаем существующие элементы в sub_frame
            for widget in sub_frame.winfo_children():
                widget.destroy()

            selected_sub_var = tk.IntVar(value=selected_sub)
            last_selected_sub_var = tk.IntVar(value=selected_sub)

            if sub_tracks:
                # Добавляем Checkbutton для сохранения SRT файла
                save_srt_var = tk.BooleanVar(value=bool(srt_value))

                def update_srt_value(apply_to_all=False):
                    new_value = 1 if save_srt_var.get() else 0

                    if apply_to_all:
                        selected_files = file_list.selection()
                        for file_item in selected_files:
                            file_id = file_list.item(file_item, 'values')[0]
                            cursor.execute('''
                                UPDATE media_info
                                SET srt = ?
                                WHERE id = ?
                            ''', (new_value, file_id))
                    else:
                        cursor.execute('''
                            UPDATE media_info
                            SET srt = ?
                            WHERE id = ?
                        ''', (new_value, id))
                    conn.commit()

                # Checkbutton для сохранения SRT
                save_srt_checkbutton = ttk.Checkbutton(
                    sub_frame, 
                    text=" Сохранить SRT-файл", 
                    variable=save_srt_var, 
                    command=lambda: update_srt_value(apply_to_all=file_list.selection()),
                    state='disabled'
                )
                save_srt_checkbutton.pack(anchor='w', padx=10, pady=5)

                # Добавляем новый Checkbutton для сохранения версии без субтитров
                save_nonsub_var = tk.BooleanVar(value=bool(nonsub_value))

                def update_nonsub_value(apply_to_all=False):
                    new_value = 1 if save_nonsub_var.get() else 0

                    if apply_to_all:
                        selected_files = file_list.selection()
                        for file_item in selected_files:
                            file_id = file_list.item(file_item, 'values')[0]
                            cursor.execute('''
                                UPDATE media_info
                                SET nonsub = ?
                                WHERE id = ?
                            ''', (new_value, file_id))
                    else:
                        cursor.execute('''
                            UPDATE media_info
                            SET nonsub = ?
                            WHERE id = ?
                        ''', (new_value, id))
                    conn.commit()

                # Checkbutton для сохранения версии без субтитров
                save_nonsub_checkbutton = ttk.Checkbutton(
                    sub_frame,
                    text=" Сохранить копию без субтитров",
                    variable=save_nonsub_var,
                    command=lambda: update_nonsub_value(apply_to_all=file_list.selection())
                )
                save_nonsub_checkbutton.pack(anchor='w', padx=10, pady=5)

                # Проверка для включения/выключения чекбоксов
                def check_enable_save_srt():
                    if selected_sub_var.get() != 0:
                        save_srt_checkbutton.config(state='normal')
                        save_nonsub_checkbutton.config(state='normal')
                    else:
                        save_srt_checkbutton.config(state='disabled')
                        save_nonsub_checkbutton.config(state='disabled')
                        if save_srt_var.get():
                            save_srt_var.set(False)
                            update_srt_value()
                        if save_nonsub_var.get():
                            save_nonsub_var.set(False)
                            update_nonsub_value()

                # Отображение субтитров
                for idx, track in enumerate(sub_tracks, start=1):
                    track_number, codec_name, language, title, forc = track
                    radio_button_frame = ttk.Frame(sub_frame)
                    radio_button = ttk.Radiobutton(
                        radio_button_frame, 
                        variable=selected_sub_var, 
                        value=track_number,
                        command=lambda: [self.update_selected_sub(id, selected_sub_var, last_selected_sub_var, file_list), check_enable_save_srt()]
                    )
                    radio_button.pack(side='left')

                    text_frame = ttk.Frame(radio_button_frame)
                    text_frame.pack(side='left', fill='x')

                    title_label = ttk.Label(
                        text_frame,
                        text=f"{title}",
                        font=("Arial", 10, "bold")
                    )
                    title_label.pack(anchor='w')

                    details_label = ttk.Label(
                        text_frame,
                        text=f"{codec_name}, {language} {forc}",
                        font=("Arial", 9)
                    )
                    details_label.pack(anchor='w')

                    radio_button_frame.pack(anchor='w', padx=10, pady=5, fill='x')

                # Проверяем состояние Checkbutton
                check_enable_save_srt()

            else:
                no_tracks_label = ttk.Label(sub_frame, text="Нет субтитров")
                no_tracks_label.pack(anchor='w', padx=10, pady=5)

        except Exception as e:
            print(f"Ошибка при отображении дорожек субтитров: {e}")


    def show_widgets(self, id, widgets_frame):
        try:
            cursor.execute('''
                SELECT start_tc, end_tc, minus, infade, outfade, selected_preset, square_position
                FROM media_info
                WHERE id = ?
            ''', (id,))
            info = cursor.fetchone()
            if info:
                start_tc, end_tc, minus, infade, outfade, selected_preset, square_position = info
                
                widgets = widgets_frame.winfo_children()
                lb_in = widgets[2]
                lb_out = widgets[4]
                lb_minus = widgets[6]
                infadespinbox = widgets[8]
                outfadespinbox = widgets[10]
                lb_kor = widgets[12]
                preset_combobox = widgets[14]

                lb_in.delete(0, tk.END)
                lb_out.delete(0, tk.END)
                lb_minus.delete(0, tk.END)
                infadespinbox.delete(0, tk.END)
                outfadespinbox.delete(0, tk.END)
                preset_combobox.delete(0, tk.END)
                lb_kor.delete(0, tk.END)

                lb_in.insert(0, start_tc)
                lb_out.insert(0, end_tc)
                lb_minus.insert(0, minus)
                infadespinbox.insert(0, infade)
                outfadespinbox.insert(0, outfade)
                preset_combobox.insert(0, selected_preset)
                lb_kor.insert(0, square_position)
            else:
                print("No data found for id:", id)
        except Exception as e:
            print(f"Error: {e}")

    def update_entry(self, event, file_list, widgets_frame):
        selected_items = file_list.selection()
        widgets = widgets_frame.winfo_children()
        lb_in = widgets[2]
        lb_out = widgets[4]
        lb_minus = widgets[6]
        infadespinbox = widgets[8]
        outfadespinbox = widgets[10]
        preset_combobox = widgets[14]
        
        if event.widget == lb_in:
            for selected_item in selected_items:
                start_tc = lb_in.get()
                id = file_list.item(selected_item, 'values')[0]
                cursor.execute('''
                    UPDATE media_info
                    SET start_tc = ?
                    WHERE id = ?
                ''', (start_tc, id))
                conn.commit()
            event.widget.master.focus_set()

        elif event.widget == lb_out:
            for selected_item in selected_items:
                id = file_list.item(selected_item, 'values')[0]
                end_tc = lb_out.get()
                cursor.execute('''
                    UPDATE media_info
                    SET end_tc = ?
                    WHERE id = ?
                ''', (end_tc, id))
                conn.commit()
            event.widget.master.focus_set()

        elif event.widget == lb_minus:
            for selected_item in selected_items:
                id = file_list.item(selected_item, 'values')[0]
                minus = lb_minus.get()
                cursor.execute('''
                    UPDATE media_info
                    SET minus = ?
                    WHERE id = ?
                ''', (minus, id))
                conn.commit()
            event.widget.master.focus_set()

        elif event.widget == preset_combobox:
            for selected_item in selected_items:
                id= file_list.item(selected_item, 'values')[0]
                selected_preset = preset_combobox.get()
                cursor.execute('''
                    UPDATE media_info
                    SET selected_preset = ?
                    WHERE id = ?
                ''', (selected_preset, id))
                conn.commit()
            event.widget.master.focus_set()
            
        elif event.widget == infadespinbox:
            for selected_item in selected_items:
                id = file_list.item(selected_item, 'values')[0]
                infade = infadespinbox.get()
                cursor.execute('''
                    UPDATE media_info
                    SET infade = ?
                    WHERE id = ?
                ''', (infade, id))
                conn.commit()
            event.widget.master.focus_set()

        elif event.widget == outfadespinbox:
            for selected_item in selected_items:
                id = file_list.item(selected_item, 'values')[0]
                outfade = outfadespinbox.get()
                cursor.execute('''
                    UPDATE media_info
                    SET outfade = ?
                    WHERE id = ?
                ''', (outfade, id))
                conn.commit()
            event.widget.master.focus_set()

    def run_media_player(self, file_list, widgets_frame):
        selected_items = file_list.selection()
        if selected_items:
            id = file_list.item(selected_items[0], 'values')[0]
            cursor.execute('''
                SELECT file_path
                FROM media_info
                WHERE id = ?
            ''', (id,))
            file_path = cursor.fetchone()[0]
            cutplayer = Cut(video_source=file_path)
            self.wait_window(cutplayer)
            self.show_widgets(id, widgets_frame)

    def kor(self, file_list, widgets_frame):
        selected_items = file_list.selection()
        if selected_items:
            id = file_list.item(selected_items[0], 'values')[0]
            cursor.execute('''
                SELECT file_path
                FROM media_info
                WHERE id = ?
            ''', (id,))
            file_path = cursor.fetchone()[0]
            conn.commit()

            delogoplayer = Delogo(video_source=file_path)
            self.wait_window(delogoplayer)

            cursor.execute('''
                SELECT square_position
                FROM media_info
                WHERE id = ?
            ''', (id,))
            conn.commit()
            square_position = cursor.fetchone()[0]

            for selected_item in selected_items:
                id = file_list.item(selected_item, 'values')[0]
                cursor.execute('''
                    UPDATE media_info
                    SET square_position = ?
                    WHERE id = ?
                ''', (square_position, id))
                conn.commit()

            self.show_widgets(id, widgets_frame)

    def remove_files(self, id):
        conn = sqlite3.connect('media_info.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT file_path_to_output
            FROM media_info 
            WHERE id = ?
        ''', (id,))
        result = cursor.fetchall()
        path_output = result[0][0]
        audio_file = os.path.join(path_output, (id) +'_stereo.m4a')
        normalize_file = os.path.join(path_output, (id) + '_normalize.m4a')    
        alpha_mask = os.path.join(path_output, (id) + '_mask.png')
        sub_file = os.path.join(path_output, (id) + '_sub.ass')
        avi_file = os.path.join(path_output, (id) + '_avi.m4v')
        file_paths = [audio_file, normalize_file, avi_file, sub_file, alpha_mask]
        for file_path in file_paths:
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    print(f"Файл {file_path} был удален.")
                except Exception as e:
                    print(f"Ошибка при удалении файла {file_path}: {e}")

    def run(self, file_list, widgets_frame):
        global process_states, file_list_states

        widgets = widgets_frame.winfo_children()
        bt_run = widgets[15]
        
        # Инициализация состояния для текущего file_list и кнопки
        process_states[file_list] = {
            'stop_event': threading.Event(),
            'process_handles': [],
            'current_id': None,
            'is_running': False  # Добавляем флаг состояния
        }
        file_list_states[file_list] = widgets_frame


        def toggle_button():
            nonlocal bt_run
            state = process_states[file_list]
            print(state)

            # Проверка, если процесс уже запущен
            if state['is_running'] and bt_run.cget("text") == "Запустить":
                print("Процесс уже запущен.")
                return

            if bt_run.cget("text") == "Запустить":
                bt_run.config(text='Стоп', style='Danger.TButton')
                state['stop_event'].clear()
                state['process_handles'] = []
                state['is_running'] = True  # Устанавливаем флаг запуска
                threading.Thread(target=self.process_files, args=(file_list, state)).start()
                state['is_running'] = False 
            else:
                bt_run.config(text='Запустить', style='Accent.TButton')
                state['stop_event'].set()
                # Останавливаем все запущенные процессы
                for p in state['process_handles']:
                    p.terminate()  # Отправляем сигнал на остановку процесса
                for p in state['process_handles']:
                    p.wait()
                state['is_running'] = False  # Сбрасываем флаг запуска после остановки

        bt_run.config(command=toggle_button)


    def update_file_list(self, file_list, id):
        conn = sqlite3.connect('media_info.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT file_name, file_path_to_output, status
            FROM media_info
            WHERE id = ?
        ''', (id,))
        rows = cursor.fetchall()
        for row in rows:
            file_name, file_path_to_output, status = row              
            file_list.insert('', 'end', values=(id, file_name, file_path_to_output, status))

    def process_files(self, file_list, state):
        while not state['stop_event'].is_set():
            selected_items = file_list.get_children()
            all_files_done = all(file_list.item(item, 'values')[3] in ["Done", "Error"] for item in selected_items)
            if all_files_done:
                widgets_frame = file_list_states[file_list]
                bt_run = widgets_frame.winfo_children()[15]
                bt_run.config(text='Запустить', style='Accent.TButton')
                break
            for selected_item in selected_items:
                if state['stop_event'].is_set():
                    break
                id = file_list.item(selected_item, 'values')[0]
                file_name = file_list.item(selected_item, 'values')[1]
                output_path = file_list.item(selected_item, 'values')[2]
                status = file_list.item(selected_item, 'values')[3]
                if status == 'Done':
                    continue
                try:
                    file_list.item(selected_item, values=(id, file_name, output_path, 'Process'))
                    render.process_files(id)
                except Exception as e:
                    print(f"Ошибка при конвертации файла {file_name}: {e}")
                    
                finally:
                    conn = sqlite3.connect('media_info.db', check_same_thread=False)
                    cursor = conn.cursor()
                    cursor.execute('''
                        SELECT status
                        FROM media_info
                        WHERE id = ?
                    ''', (id,))
                    status = cursor.fetchall()[0]
                    file_list.item(selected_item, values=(id, file_name, output_path, status))
                    self.remove_files(id)

            remaining_files = any(file_list.item(item, 'values')[3] not in ["Done", "Error"] for item in file_list.get_children())
            if not remaining_files:
                widgets_frame = file_list_states[file_list]
                bt_run = widgets_frame.winfo_children()[15]
                bt_run.config(text='Запустить', style='Accent.TButton')
                break 
            time.sleep(1)

    def on_drag_enter(self, event):
        event.widget.focus_set()
        event.widget.configure(bg='lightblue')

    def on_drag_leave(self, event):
        event.widget.configure(bg='white')

    def on_drop(self, event, file_list, tab):
        data = event.data.strip()
        pattern = r'({[^}]+}|[^ ]+)'
        files = re.findall(pattern, data)
        files = [file.strip('{}') for file in files]
        progress_window = tk.Toplevel(self)
        progress_window.title("Обработка файлов")
        pywinstyles.apply_style(progress_window, 'mica')
        tk.Label(progress_window, text="Получаем медиа информацию...").pack(pady=10)
        progress_bar = ttk.Progressbar(progress_window, orient="horizontal", length=300, mode="determinate")
        progress_bar.pack(pady=10)
        progress_bar['value'] = 0
        total_files = len(files)

        def start_processing():
            for file in files:
                file = file.strip()
                if os.path.isfile(file):
                    insert_media_info(db_path, file, tab)
                    self.load_data(file, file_list)
                    progress_bar['value'] += 100 / total_files
            progress_window.destroy()

        threading.Thread(target=start_processing).start()

    def go_to_source_folder(self, event, file_list):
        selected_items = file_list.selection()
        if selected_items:
            first_item = selected_items[0]
            id = file_list.item(first_item, 'values')[0]
            self.cursor.execute('''
                SELECT file_path
                FROM media_info
                WHERE id = ?
            ''', (id,))
            file_path = self.cursor.fetchone()[0]
            folder_path = os.path.dirname(file_path).replace("/", "\\")
            subprocess.Popen(['explorer', folder_path])

    def go_to_destination_folder(self, event, file_list):
        selected_items = file_list.selection()
        if selected_items:
            first_item = selected_items[0]
            destination_folder = file_list.item(first_item, 'values')[2]
            destination_folder = destination_folder.replace("/", "\\")
            subprocess.Popen(['explorer', destination_folder])

    def open_mediainfo(self, file_list):
        selected_items = file_list.selection()
        if selected_items:
            first_item = selected_items[0]
            id = file_list.item(first_item, 'values')[0]
            self.cursor.execute('''
                SELECT file_path
                FROM media_info
                WHERE id = ?
            ''', (id,))
            file_path = self.cursor.fetchone()[0]
            mediainfo_exe_path = r'C:\Program Files (x86)\K-Lite Codec Pack\Tools\mediainfo.exe'
            if os.path.exists(mediainfo_exe_path):
                subprocess.Popen([mediainfo_exe_path, file_path])
            else:
                print("Ошибка: Не удалось найти mediainfo.exe")

    def open_log(self, file_list):
        selected_items = file_list.selection()
        if selected_items:
            first_item = selected_items[0]
            id = file_list.item(first_item, 'values')[0]
            self.cursor.execute('''
                SELECT file_name
                FROM media_info
                WHERE id = ?
            ''', (id,))
            file_name = self.cursor.fetchone()[0]
            file_name = id + '_' + file_name + '.log' 
            log_dir = os.path.join(os.path.dirname(__file__), 'logs')
            file_path = os.path.join(log_dir, file_name)
            if os.path.exists(file_path):
                subprocess.Popen(['notepad.exe', file_path])
            else:
                print("Ошибка: Лог-файл не найден.")

    def reset_status(self, event, file_list):
        selected_items = file_list.selection()
        for selected_item in selected_items:
            id = file_list.item(selected_item, 'values')[0]
            file_name = file_list.item(selected_item, 'values')[1]
            output_path = file_list.item(selected_item, 'values')[2]
            status = 'Ready'
            self.cursor.execute("UPDATE media_info SET status=? WHERE id=?", (status, id))
            self.conn.commit()
            file_list.item(selected_item, values=(id, file_name, output_path, status))

    def show_context_menu(self, event, file_list, audio_frame, sub_frame, widgets_frame, info_text):
        selected_items = file_list.selection()
        if selected_items:
            context_menu = tk.Menu(self, tearoff=0)
            context_menu.add_command(label="Открыть", command=lambda: self.open_selected_file(file_list))
            context_menu.add_command(label="MediaInfo", command=lambda: self.open_mediainfo(file_list))
            context_menu.add_command(label="Log", command=lambda: self.open_log(file_list))
            context_menu.add_command(label="Удалить", command=lambda: self.delete_selected_file(file_list, audio_frame, sub_frame, widgets_frame, info_text))
            context_menu.add_command(label="Сбросить статус", command=lambda: self.reset_status(event, file_list))
            context_menu.add_command(label="Перейти в исходную папку", command=lambda: self.go_to_source_folder(event, file_list))
            context_menu.add_command(label="Перейти в папку назначения", command=lambda: self.go_to_destination_folder(event, file_list))
            context_menu.tk_popup(event.x_root, event.y_root)

    def select_file(self, event, file_list, audio_frame, sub_frame, widgets_frame, info_text):
        item = file_list.identify_row(event.y)
        if item not in file_list.selection():
            file_list.selection_set(item)
        self.show_context_menu(event, file_list, audio_frame, sub_frame, widgets_frame, info_text)

    def file_selection(self, file_list, audio_frame, sub_frame, widgets_frame, info_text):
        selected_items = file_list.selection()
        if selected_items:
            id = file_list.item(selected_items[0], 'values')[0]
            self.show_audio_tracks(id, audio_frame, file_list)
            self.show_sub_tracks(id, sub_frame, file_list)
            self.show_widgets(id, widgets_frame)
            self.show_info(id, info_text)

    def open_selected_file(self, file_list):
        selected_items = file_list.selection()
        if selected_items:
            first_item = selected_items[0]
            id = file_list.item(first_item, 'values')[0]
            self.cursor.execute('''
                SELECT file_path
                FROM media_info
                WHERE id = ?
            ''', (id,))
            file_path = self.cursor.fetchone()[0]
            os.startfile(file_path)

    def select_all(self, file_list):
        file_list.selection_remove(file_list.selection())
        file_list.selection_add(file_list.get_children())
        return 'break'

    def create_tab(self, tab_num):
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text=f"Task {tab_num}")

        tab.grid_rowconfigure(0, weight=0)
        tab.grid_rowconfigure(1, weight=0)
        tab.grid_rowconfigure(2, weight=1)
        tab.grid_rowconfigure(3, weight=1)
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_columnconfigure(1, weight=1)
        tab.grid_columnconfigure(2, weight=1)

        paned = ttk.PanedWindow(tab)
        paned.grid(row=1, rowspan=3, column=0, columnspan=2, padx=5, pady=5, sticky="nsew")
        pane = ttk.Frame(paned)
        paned.add(pane, weight=1)

        # Список файлов
        tree_frame = ttk.Frame(pane)
        tree_frame.pack(expand=True, fill="both", padx=5, pady=5)
        tree_scroll = ttk.Scrollbar(tree_frame)
        tree_scroll.pack(side="right", fill="y")
        file_list = ttk.Treeview(tree_frame, columns=('id', 'Name', 'PathOut', 'Status'),
                                 selectmode='extended', yscrollcommand=tree_scroll.set, height=27)
        file_list.pack(expand=True, fill="both")
        tree_scroll.config(command=file_list.yview)

        # Настройка колонок
        file_list.column("#0", width=0, stretch=tk.NO)
        file_list.column('id', width=0, stretch=tk.NO)
        file_list.column('Name', width=470)
        file_list.column('PathOut', width=450)
        file_list.column('Status', width=55)
        file_list.heading('Name', text='Файлы', anchor='w')
        file_list.heading('PathOut', text='Папка вывода', anchor='w')
        file_list.heading('Status', text='Статус', anchor='w')
        file_list['displaycolumns'] = ('Name', 'PathOut', 'Status')

        # Привязки событий
        file_list.bind("<<TreeviewSelect>>", lambda e: self.file_selection(file_list, audio_frame, sub_frame, widgets_frame, info_text))
        file_list.bind("<Delete>", lambda e: self.delete_selected_file(file_list, audio_frame, sub_frame, widgets_frame, info_text))
        file_list.drop_target_register(DND_FILES)
        file_list.dnd_bind('<<Drop>>', lambda e: self.on_drop(e, file_list, tab_num))
        file_list.bind('<Double-1>', lambda e: self.open_selected_file(file_list))
        file_list.bind("<Button-3>", lambda e: self.select_file(e, file_list, audio_frame, sub_frame, widgets_frame, info_text))
        file_list.bind("<Control-a>", lambda e: self.select_all(file_list))
        # Загрузка данных в Treeview
        self.load_data_into_treeview(file_list, tab_num)

        # Кнопки
        bt_inp = ttk.Button(tab, text='Добавить файлы', command=lambda: self.f_inp(file_list, tab_num))
        bt_inp.grid(row=0, column=0, padx=(10, 0), pady=(15, 2), sticky="w")

        bt_out = ttk.Button(tab, text='Выбрать папку вывода', command=lambda: self.f_out(file_list))
        bt_out.grid(row=0, column=2, padx=(10, 10), pady=(10, 2), sticky="e")

        # Аудио, субтитры, информация
        audio_frame = self.create_audio_frame(tab)
        sub_frame = self.create_sub_frame(tab)
        info_text = self.create_info_frame(tab)
        widgets_frame = self.create_widgets_frame(tab, file_list)
  
    def create_audio_frame(self, tab):
        a_frame = ttk.LabelFrame(tab, text='Аудиодорожки')
        a_frame.grid(row=2, column=2, columnspan=1, padx=5, pady=(2, 10), sticky="nsew")
        a_canvas = tk.Canvas(a_frame)
        a_canvas.pack(side="left", fill="both", expand=True)
        a_scrollbar = ttk.Scrollbar(a_frame, orient="vertical", command=a_canvas.yview)
        a_scrollbar.pack(side="right", fill="y")
        audio_frame = ttk.Frame(a_canvas)
        audio_frame.bind("<Configure>", lambda e: a_canvas.configure(scrollregion=a_canvas.bbox("all")))
        a_canvas.create_window((0, 0), window=audio_frame, anchor="nw")
        a_canvas.configure(yscrollcommand=a_scrollbar.set)
        return audio_frame

    def create_sub_frame(self, tab):
        s_frame = ttk.LabelFrame(tab, text='Субтитры')
        s_frame.grid(row=3, column=2, columnspan=1, padx=5, pady=(2, 10), sticky="nsew")
        s_canvas = tk.Canvas(s_frame)
        s_canvas.pack(side="left", fill="both", expand=True)
        s_scrollbar = ttk.Scrollbar(s_frame, orient="vertical", command=s_canvas.yview)
        s_scrollbar.pack(side="right", fill="y")
        sub_frame = ttk.Frame(s_canvas)
        sub_frame.bind("<Configure>", lambda e: s_canvas.configure(scrollregion=s_canvas.bbox("all")))
        s_canvas.create_window((0, 0), window=sub_frame, anchor="nw")
        s_canvas.configure(yscrollcommand=s_scrollbar.set)
        return sub_frame

    def create_info_frame(self, tab):
        info_frame = ttk.LabelFrame(tab, text='Видеодорожка')
        info_frame.grid(row=1, column=2, columnspan=1, padx=5, pady=(2, 10), sticky="nsew")
        info_text = ttk.Label(info_frame, text='', width=12, anchor='w', justify='left')
        info_text.pack(expand=True, fill="both", side=tk.LEFT, padx=(10, 0), pady=(5, 10))
        return info_text

    def create_widgets_frame(self, tab, file_list):
        widgets_frame = ttk.Frame(tab)
        widgets_frame.grid(row=4, column=0, columnspan=3, padx=10, pady=(10, 10), sticky="nsew")

        bt_cut = ttk.Button(widgets_frame, text='CUT', width=6, command=lambda: self.run_media_player(file_list, widgets_frame))
        bt_cut.pack(expand=True, fill="both", side=tk.LEFT, padx=(0, 5), pady=(5, 15))
        
        lb_in_text = ttk.Label(widgets_frame, text='Обрезать от:', width=11, anchor='w', justify='left')
        lb_in_text.pack(expand=True, fill="both", side=tk.LEFT, padx=(5, 0), pady=(5, 15))

        lb_in = ttk.Entry(widgets_frame, justify='left', width=11)
        lb_in.pack(expand=True, fill="both", side=tk.LEFT, padx=(0, 5), pady=(5, 15))
        lb_in.bind("<Return>", lambda e: self.update_entry(e, file_list, widgets_frame))

        # До
        lb_out_text = ttk.Label(widgets_frame, text='до:', width=4, anchor='e', justify='left')
        lb_out_text.pack(expand=True, fill="both", side=tk.LEFT, padx=(0, 5), pady=(5, 15))

        lb_out = ttk.Entry(widgets_frame, justify='left', width=11)
        lb_out.pack(expand=True, fill="both", side=tk.LEFT, padx=(0, 0), pady=(5, 15))
        lb_out.bind("<Return>", lambda e: self.update_entry(e, file_list, widgets_frame))

        lb_minus_text = ttk.Label(widgets_frame, text='-', width=2, anchor='e', justify='left')
        lb_minus_text.pack(expand=True, fill="both", side=tk.LEFT, padx=(0, 5), pady=(5, 15))

        lb_minus = ttk.Entry(widgets_frame, justify='left', width=11)
        lb_minus.pack(expand=True, fill="both", side=tk.LEFT, padx=(0, 10), pady=(5, 15))
        lb_minus.bind("<Return>", lambda e: self.update_entry(e, file_list, widgets_frame))

        # Fade in
        infade_text = ttk.Label(widgets_frame, text='Fade in:', width=10, anchor='e', justify='left')
        infade_text.pack(expand=True, fill="both", side=tk.LEFT, padx=(0, 5), pady=(5, 15))

        infadespinbox = ttk.Spinbox(widgets_frame, from_=0.0, to=100.0, width=5)
        infadespinbox.pack(expand=True, fill="both", side=tk.LEFT, padx=(0, 5), pady=(5, 15))
        infadespinbox.bind("<Return>", lambda e: self.update_entry(e, file_list, widgets_frame))

        # Out
        outfade_text = ttk.Label(widgets_frame, text='out:', width=5, anchor='e', justify='left')
        outfade_text.pack(expand=True, fill="both", side=tk.LEFT, padx=(0, 5), pady=(5, 15))

        outfadespinbox = ttk.Spinbox(widgets_frame, from_=0.0, to=100.0, width=5)
        outfadespinbox.pack(expand=True, fill="both", side=tk.LEFT, padx=(0, 10), pady=(5, 15))
        outfadespinbox.bind("<Return>", lambda e: self.update_entry(e, file_list, widgets_frame))

        # DELOGO
        bt_kor = ttk.Button(widgets_frame, text='DELOGO', width=8, command=lambda: self.kor(file_list, widgets_frame))
        bt_kor.pack(expand=True, fill="both", side=tk.LEFT, padx=(20, 10), pady=(5, 15))

        # Координаты
        lb_kor = ttk.Entry(widgets_frame, justify='left', width=18)
        lb_kor.pack(expand=True, fill="both", side=tk.LEFT, padx=(0, 5), pady=(5, 15))

        # Пресет
        preset_text = ttk.Label(widgets_frame, text='Пресет:', width=9, anchor='e', justify='left')
        preset_text.pack(expand=True, fill="both", side=tk.LEFT, padx=(0, 5), pady=(5, 15))

        preset_combobox = ttk.Combobox(widgets_frame, values=["10 Mbps", "6 Mbps", "COPY", "AAC", "SRT"], width=8)
        preset_combobox.pack(expand=True, fill="both", side=tk.LEFT, padx=(0, 10), pady=(5, 15))
        preset_combobox.bind("<<ComboboxSelected>>", lambda e: self.update_entry(e, file_list, widgets_frame))

        # Запустить
        bt_run2 = ttk.Button(widgets_frame, text='Запустить', command=lambda: self.run(file_list, widgets_frame), style="Accent.TButton")
        bt_run2.pack(expand=True, fill="both", side=tk.LEFT, padx=(20, 0), pady=(5, 15))
        bt_run2.config(state='normal')
        self.run(file_list, widgets_frame)
        
        return widgets_frame

    def close_db_connection(self):
        self.destroy()

class Delogo(tk.Toplevel):
    def __init__(self, video_source=None):
        super().__init__()
        self.title(video_source)
        self.option_add("*tearOff", False)
        self.geometry("1300x850")
        pywinstyles.apply_style(self, 'mica')
        
        self.video_source = video_source
        self.cap = None
        self.playing = False
        self.paused = True
        self.current_frame = 0
        self.total_frames = 0     
        self.video_width = 1280
        self.video_height = 720

        # Database setup
        self.db_connection = sqlite3.connect('media_info.db')
        self.db_cursor = self.db_connection.cursor()

        # Variables for rectangle selection
        self.rect_start_x = None
        self.rect_start_y = None
        self.rect_end_x = None
        self.rect_end_y = None
        self.scale_x = 1
        self.scale_y = 1
        self.x_offset = 0
        self.y_offset = 0
        self.square_position = None
        self.create_widgets()
        self.open_file()

    def create_widgets(self):
        # Create a frame for the video
        self.video_frame = tk.Frame(self, width=self.video_width, height=self.video_height, bg='black')
        self.video_frame.pack(pady=(20, 20), side=tk.TOP)

        self.canvas = tk.Canvas(self.video_frame, width=self.video_width, height=self.video_height, bg='black')
        self.canvas.pack()
        self.canvas.bind("<Button-1>", self.on_mouse_press)
        self.canvas.bind("<B1-Motion>", self.on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_mouse_release)

        self.time_scale = ttk.Scale(self, from_=0, to=100000, orient='horizontal')
        self.time_scale.pack(fill="both", side=tk.TOP, padx=20)
        self.time_scale.bind("<B1-Motion>", self.on_scale_drag)

        self.kor_text = ttk.Label(self, text='Координаты:')
        self.kor_text.pack(side=tk.LEFT, padx=(20, 5))
        
        self.lb_kor = ttk.Entry(self, width=18)
        self.lb_kor.pack(side=tk.LEFT, padx=20)

        self.clear_button = ttk.Button(self, text="Очистить", command=self.clear_square_position)
        self.clear_button.pack(side=tk.LEFT, padx=10)

        self.save_button = ttk.Button(self, text="Сохранить", command=self.save_to_database, style="Accent.TButton")
        self.save_button.pack(side=tk.RIGHT, padx=20)
    
    def open_file(self):
        if self.video_source:
            self.cap = cv2.VideoCapture(self.video_source)
            self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
            self.time_scale.config(to=self.total_frames)     
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            self.current_frame = 0
            self.update_frame()
            self.next_frame()
            self.insert_entry()

    def clear_square_position(self):
        self.db_cursor.execute('''
            UPDATE media_info
            SET square_position = ''
            WHERE file_path = ?
        ''', (self.video_source,))
        self.db_connection.commit()
        self.lb_kor.delete(0, tk.END)
        self.square_position = None

    def next_frame(self):
        if self.cap:
            self.current_frame = min(self.total_frames - 1, self.current_frame + 1)
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, self.current_frame)
            self.update_frame(immediate=True)

    def on_scale_drag(self, event):
        if self.cap:
            frame_num = int(self.time_scale.get())
            if frame_num < self.total_frames:
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
                self.current_frame = frame_num
                self.update_frame(immediate=True)
    
    def update_frame(self, immediate=False):
        if self.cap:
            if not self.paused or immediate:
                ret, frame = self.cap.read()
                if ret:
                    frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    
                    # Calculate the aspect ratio
                    frame_height, frame_width, _ = frame.shape
                    frame_aspect = frame_width / frame_height
                    target_aspect = self.video_width / self.video_height
                    
                    if (self.video_width, self.video_height) != (frame_width, frame_height):
                        if frame_aspect > target_aspect:
                            new_width = self.video_width
                            new_height = int(new_width / frame_aspect)
                        else:
                            new_height = self.video_height
                            new_width = int(new_height * frame_aspect)                        
                        frame = cv2.resize(frame, (new_width, new_height))

                        # Calculate scale factors for coordinate transformation
                        self.scale_x = frame_width / new_width
                        self.scale_y = frame_height / new_height

                        # Calculate offsets
                        self.x_offset = (self.video_width - new_width) // 2
                        self.y_offset = (self.video_height - new_height) // 2

                        # Create a black background
                        black_frame = Image.new('RGB', (self.video_width, self.video_height), (0, 0, 0))
                        frame_pil = Image.fromarray(frame)
                        black_frame.paste(frame_pil, (self.x_offset, self.y_offset))
                        frame = black_frame
                    else:
                        frame = Image.fromarray(frame)
                        self.scale_x = 1
                        self.scale_y = 1
                        self.x_offset = 0
                        self.y_offset = 0

                    # Convert to PhotoImage and update Canvas
                    photo = ImageTk.PhotoImage(image=frame)
                    self.canvas.create_image(0, 0, anchor=tk.NW, image=photo)
                    self.canvas.image = photo
                    
                    self.current_frame = int(self.cap.get(cv2.CAP_PROP_POS_FRAMES))
                    self.time_scale.set(self.current_frame)
                    
                    # Draw rectangle if it exists
                    if self.rect_start_x is not None and self.rect_start_y is not None:
                        self.draw_rectangle()
                else:
                    self.pause_media()
            
            if not self.playing:
                self.after(30, self.update_frame)
    
    def draw_rectangle(self):
        self.canvas.delete("rect")
        if self.rect_start_x is not None and self.rect_start_y is not None and self.rect_end_x is not None and self.rect_end_y is not None:
            self.canvas.create_rectangle(
                self.rect_start_x, self.rect_start_y,
                self.rect_end_x, self.rect_end_y,
                outline="#217346", width=3, tags="rect"
            )

    def on_mouse_press(self, event):
        self.rect_start_x = event.x
        self.rect_start_y = event.y
        self.rect_end_x = None
        self.rect_end_y = None

    def on_mouse_drag(self, event):
        self.rect_end_x = event.x
        self.rect_end_y = event.y
        if self.rect_start_x is not None and self.rect_start_y is not None:
            self.draw_rectangle()

    def on_mouse_release(self, event):
        self.rect_end_x = event.x
        self.rect_end_y = event.y
        # Calculate rectangle coordinates (x, y, w, h)
        if self.rect_start_x is not None and self.rect_start_y is not None:
            x1 = (self.rect_start_x - self.x_offset) * self.scale_x
            y1 = (self.rect_start_y - self.y_offset) * self.scale_y
            x2 = (self.rect_end_x - self.x_offset) * self.scale_x
            y2 = (self.rect_end_y - self.y_offset) * self.scale_y
            self.db_cursor.execute("SELECT resolution FROM media_info WHERE file_path=?", (self.video_source,))
            resolution = self.db_cursor.fetchone()[0]
            width, height = resolution.split('x')
            kor = round(int(width) * 0.01)
            x = int(min(x1, x2)) - kor
            if x <= 0:
                x = 1
            y = int(min(y1, y2)) - kor
            if y <= 0:
                y = 1
            w = int(abs(x2 - x1)) + kor * 2
            h = int(abs(y2 - y1)) + kor * 2

            if (int(x) + int(w)) >= int(width):
                w = int(width) - int(x) - 1
            if (int(y) + int(h)) >= int(height):
                h = int(height) - int(y) - 1
            self.square_position = (x, y, w, h)
            self.update_coordinates_entry(self.square_position)

    def update_coordinates_entry(self, coordinates):
        self.lb_kor.delete(0, tk.END)
        self.lb_kor.insert(0, str(coordinates))
    
    def insert_entry(self):
        self.lb_kor.delete(0, tk.END)
        self.db_cursor.execute("SELECT square_position FROM media_info WHERE file_path=?", (self.video_source,))
        square_position = self.db_cursor.fetchone()[0]
        self.lb_kor.insert(0, square_position)

    def save_to_database(self):
        square_position = str(self.square_position) if self.square_position else ''
        self.db_cursor.execute('''
            UPDATE media_info
            SET square_position = ?
            WHERE file_path = ?
        ''', (square_position, self.video_source))
        self.db_connection.commit()
        self.on_closing()

    def stop_media(self):
        self.playing = False
        self.paused = False
        self.canvas.delete("all")

    def on_closing(self):
        self.db_connection.close()
        self.destroy()

class Cut(tk.Toplevel):
    def __init__(self, video_source=None):
        super().__init__()
        self.title(video_source)
        self.option_add("*tearOff", False)
        self.geometry("1300x900")
        pywinstyles.apply_style(self, 'mica')
        
        self.video_source = video_source
        self.cap = None
        self.playing = False
        self.paused = False
        self.current_frame = 0
        self.total_frames = 0
        
        self.video_width = 1280
        self.video_height = 720

        # Database setup
        self.db_connection = sqlite3.connect('media_info.db')
        self.db_cursor = self.db_connection.cursor()

        # New attributes for start/end labels on the time scale
        self.start_line = None
        self.end_line = None
        
        self.create_widgets()
        self.open_file()
        self.load_start_tc()
        self.load_end_tc()
    
    def create_widgets(self):
        # Create a frame for the video
        self.video_frame = tk.Frame(self, width=self.video_width, height=self.video_height, bg='black')
        self.video_frame.pack(pady=(20, 0), side=tk.TOP)
        
        self.video_label = ttk.Label(self.video_frame)
        self.video_label.pack()
        
        self.entry_frame = tk.Frame(self)
        self.entry_frame.pack(expand=True, fill="both")
        
        self.time_entry = ttk.Entry(self.entry_frame, width=11)
        self.time_entry.pack(side=tk.LEFT, padx=20)
        self.time_entry.bind("<Return>", self.on_entry_change)

        self.duration_entry = ttk.Entry(self.entry_frame, width=11)
        self.duration_entry.pack(side=tk.RIGHT, padx=20)
        
        self.start_button = ttk.Button(self.entry_frame, text="[", command=self.save_start_tc)
        self.start_button.pack(side=tk.LEFT, padx=5)
        self.start_tc_label = ttk.Label(self.entry_frame, text="")
        self.start_tc_label.pack(side=tk.LEFT, padx=5)
        
        self.end_button = ttk.Button(self.entry_frame, text="]", command=self.save_end_tc)
        self.end_button.pack(side=tk.RIGHT, padx=5)
        self.end_tc_label = ttk.Label(self.entry_frame, text="")
        self.end_tc_label.pack(side=tk.RIGHT, padx=5)
        
        # Create a Canvas for the time scale
        self.time_scale_frame = tk.Frame(self)
        self.time_scale_frame.pack(fill="both", side=tk.TOP, padx=20)
        self.time_scale = ttk.Scale(self.time_scale_frame, from_=0, to= 100000, orient='horizontal')
        self.time_scale.pack(fill="both", side=tk.TOP, padx=20)
        self.time_scale.bind("<ButtonRelease-1>", self.on_scale_change)
        self.time_scale.bind("<B1-Motion>", self.on_scale_drag)
        
        # Create a frame for the control buttons and time display
        self.controls_frame = tk.Frame(self)
        self.controls_frame.pack(expand=True)
        
        self.prev_15_frames_button = ttk.Button(self.controls_frame, text="<<", command=self.prev_15_frames)
        self.prev_15_frames_button.pack(side=tk.LEFT, padx=5)
        
        self.prev_frame_button = ttk.Button(self.controls_frame, text="<", command=self.prev_frame)
        self.prev_frame_button.pack(side=tk.LEFT, padx=5)
        
        self.play_pause_button = ttk.Button(self.controls_frame, text="Play", command=self.toggle_play_pause)
        self.play_pause_button.pack(side=tk.LEFT, padx=5)
        
        self.next_frame_button = ttk.Button(self.controls_frame, text=">", command=self.next_frame)
        self.next_frame_button.pack(side=tk.LEFT, padx=5)
        
        self.next_15_frames_button = ttk.Button(self.controls_frame, text=">>", command=self.next_15_frames)
        self.next_15_frames_button.pack(side=tk.LEFT, padx=5)
    
    def open_file(self):
        if self.video_source:
            self.cap = cv2.VideoCapture(self.video_source)
            self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
            self.time_scale.config(to=self.total_frames)     
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            self.current_frame = 0
            self.update_frame()
            self.update_time_entry()
            self.update_duration_entry()
            self.play_media()
            self.pause_media()
    
    def play_media(self):
        if self.video_source:
            if not self.playing:
                self.playing = True
                self.paused = False
                self.play_pause_button.config(text="Pause")
                self.update_frame()
            elif self.paused:
                self.paused = False
                self.play_pause_button.config(text="Pause")

    def pause_media(self):
        if self.playing and not self.paused:
            self.paused = True
            self.play_pause_button.config(text="Play")

    def toggle_play_pause(self):
        if self.playing and not self.paused:
            self.pause_media()
        elif not self.playing:
            self.play_media()
        elif self.paused:
            self.play_media()
    
    def prev_frame(self):
        if self.cap:
            self.current_frame = max(0, self.current_frame - 2)
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, self.current_frame)
            self.update_frame(immediate=True)
    
    def next_frame(self):
        if self.cap:
            self.current_frame = min(self.total_frames - 1, self.current_frame + 1)
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, self.current_frame)
            self.update_frame(immediate=True)
    
    def prev_15_frames(self):
        if self.cap:
            self.current_frame = max(0, self.current_frame - 16)
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, self.current_frame)
            self.update_frame(immediate=True)
    
    def next_15_frames(self):
        if self.cap:
            self.current_frame = min(self.total_frames - 1, self.current_frame + 15)
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, self.current_frame)
            self.update_frame(immediate=True)
    
    def on_scale_change(self, event):
        if self.cap:
            frame_num = int(self.time_scale.get())
            if frame_num < self.total_frames:
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
                self.current_frame = frame_num
                if not self.playing:
                    self.update_frame()
    
    def on_scale_drag(self, event):
        self.pause_media()
        if self.cap:
            frame_num = int(self.time_scale.get())
            if frame_num < self.total_frames:
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
                self.current_frame = frame_num
                self.update_frame(immediate=True)
    
    def on_entry_change(self, event):
        self.pause_media()
        try:
            if self.cap:
                # Извлечение времени из Entry
                time_str = self.time_entry.get()
                h, m, s = map(float, time_str.split(':'))
                frame_num = int((h * 3600 + m * 60 + s) * self.cap.get(cv2.CAP_PROP_FPS))
                
                # Проверка, не превышает ли frame_num общую продолжительность
                if frame_num >= self.total_frames:
                    frame_num = self.total_frames - 1
                
                if 0 <= frame_num < self.total_frames:
                    self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
                    self.current_frame = frame_num
                    self.update_frame(immediate=True)
        except ValueError:
            print("Invalid time format. Please use HH:MM:SS.mmm")
    
    def update_frame(self, immediate=False):
        if self.cap and (self.playing or immediate):
            if not self.paused or immediate:
                ret, frame = self.cap.read()
                if ret:
                    frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    
                    # Calculate the aspect ratio
                    frame_height, frame_width, _ = frame.shape
                    frame_aspect = frame_width / frame_height
                    target_aspect = self.video_width / self.video_height
                    
                    if (self.video_width, self.video_height) != (frame_width, frame_height):
                        if frame_aspect > target_aspect:
                            new_width = self.video_width
                            new_height = int(new_width / frame_aspect)
                        else:
                            new_height = self.video_height
                            new_width = int(new_height * frame_aspect)
                        
                        frame = cv2.resize(frame, (new_width, new_height))

                        # Create a black background
                        black_frame = Image.new('RGB', (self.video_width, self.video_height), (0, 0, 0))
                        frame_pil = Image.fromarray(frame)
                        x_offset = (self.video_width - new_width) // 2
                        y_offset = (self.video_height - new_height) // 2
                        black_frame.paste(frame_pil, (x_offset, y_offset))
                        frame = black_frame
                    else:
                        frame = Image.fromarray(frame)
                    
                    photo = ImageTk.PhotoImage(image=frame)
                    self.video_label.configure(image=photo)
                    self.video_label.image = photo
                    
                    self.current_frame = int(self.cap.get(cv2.CAP_PROP_POS_FRAMES))
                    self.time_scale.set(self.current_frame)
                    self.update_time_entry()
                else:
                    self.pause_media()
            
            if self.playing and not immediate:
                self.after(30, self.update_frame)

    def update_time_entry(self):
        if self.cap:
            fps = self.cap.get(cv2.CAP_PROP_FPS)
            current_time = self.current_frame / fps
            hours, remainder = divmod(current_time, 3600)
            minutes, seconds = divmod(remainder, 60)
            milliseconds = int((seconds - int(seconds)) * 1000)
            formatted_time = f"{int(hours):02}:{int(minutes):02}:{int(seconds):02}.{milliseconds:03}"
            self.time_entry.delete(0, tk.END)
            self.time_entry.insert(0, formatted_time)
    
    def update_duration_entry(self):
        if self.cap:
            fps = self.cap.get(cv2.CAP_PROP_FPS)
            total_time = self.total_frames / fps
            hours, remainder = divmod(total_time, 3600)
            minutes, seconds = divmod(remainder, 60)
            milliseconds = int((seconds - int(seconds)) * 1000)
            formatted_duration = f"{int(hours):02}:{int(minutes):02}:{int(seconds):02}.{milliseconds:03}"
            self.duration_entry.delete(0, tk.END)
            self.duration_entry.insert(0, formatted_duration)

    def save_start_tc(self):
        try:
            start_tc = self.time_entry.get()
            file_path = self.video_source
            self.db_cursor.execute("UPDATE media_info SET start_tc=? WHERE file_path=?", (start_tc, file_path))
            self.db_connection.commit()
            self.start_tc_label.config(text=f"{start_tc}")

        except Exception as e:
            print(f"Error saving start timecode to database: {e}")
    
    def load_start_tc(self):
        if self.video_source:
            self.db_cursor.execute("SELECT start_tc FROM media_info WHERE file_path=?", (self.video_source,))
            result = self.db_cursor.fetchone()
            if result:
                start_tc = result[0]
                self.start_tc_label.config(text=f"{start_tc}")
            else:
                self.start_tc_label.config(text="")

    def save_end_tc(self):
        try:
            end_tc = self.time_entry.get()
            file_path = self.video_source
            self.db_cursor.execute("UPDATE media_info SET end_tc=? WHERE file_path=?", (end_tc, file_path))
            self.db_connection.commit()
            self.end_tc_label.config(text=f"{end_tc}")

        except Exception as e:
            print(f"Error saving end timecode to database: {e}")
    
    def load_end_tc(self):
        if self.video_source:
            self.db_cursor.execute("SELECT end_tc FROM media_info WHERE file_path=?", (self.video_source,))
            result = self.db_cursor.fetchone()
            if result:
                end_tc = result[0]
                self.end_tc_label.config(text=f"{end_tc}")
            else:
                self.end_tc_label.config(text="")

    def convert_timecode_to_frame(self, timecode):
        h, m, s = map(float, timecode.split(':'))
        return int((h * 3600 + m * 60 + s) * self.cap.get(cv2.CAP_PROP_FPS))
    
    def stop_media(self):
        self.playing = False
        self.paused = False
        self.video_label.config(image='')

    def on_closing(self):
        self.db_connection.close()
        self.destroy()

if __name__ == "__main__":
    app = App()
    app.mainloop()