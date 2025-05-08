import os
from flask import Flask, render_template, request, redirect, url_for
from google.cloud import storage
from dotenv import load_dotenv
from flask_mysqldb import MySQL
from werkzeug.utils import secure_filename
import uuid # Để tạo tên tệp duy nhất
from flask import current_app
import pymysql.cursors 
load_dotenv()

app = Flask(__name__)

# Thông tin cấu hình từ .env
BUCKET_NAME = os.getenv("BUCKET_NAME")

app.config['MYSQL_HOST'] = '34.56.229.234'  # Thay thế bằng IP của VM MariaDB
app.config['MYSQL_USER'] = 'root'  # Sử dụng người dùng mới
app.config['MYSQL_PASSWORD'] = ''  # KHÔNG CÓ MẬT KHẨU
app.config['MYSQL_DB'] = 'web'

mysql = MySQL(app)

def connect_to_db():
    try:
        conn = mysql.connection  # Lấy đối tượng kết nối
        cur = conn.cursor()
        cur.execute("SELECT 1")  # Kiểm tra kết nối
        cur.close()
        return conn
    except Exception as e:
        print(f"Lỗi kết nối Database: {e}")
        return None



def init_db():
    # Lấy thông tin cấu hình database từ app.config
    db_host = current_app.config['MYSQL_HOST']
    db_user = current_app.config['MYSQL_USER']
    db_password = current_app.config['MYSQL_PASSWORD']
    db_name = current_app.config['MYSQL_DB']

    conn = None # Khởi tạo biến kết nối
    try:
        # Tạo kết nối database thủ công chỉ cho mục đích khởi tạo
        # Sử dụng pymysql trực tiếp
        conn = pymysql.connect(
            host=db_host,
            user=db_user,
            password=db_password,
            database=db_name,
            # Có thể thêm các tham số khác nếu cần, ví dụ: port
            # port=current_app.config['MYSQL_PORT']
            cursorclass=pymysql.cursors.DictCursor 
        )
        print("Kết nối Database thành công cho init_db!") # Log để debug

        with conn.cursor() as cursor:
            # Câu lệnh SQL để tạo bảng nếu chưa tồn tại
            create_table_sql = """
            CREATE TABLE IF NOT EXISTS images (
                id INT AUTO_INCREMENT PRIMARY KEY,
                filename VARCHAR(255) NOT NULL,
                gcs_path VARCHAR(512) NOT NULL,
                public_url VARCHAR(1024),
                caption VARCHAR(255),
                uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
            cursor.execute(create_table_sql)
        conn.commit() # Commit thay đổi
        current_app.logger.info("Khởi tạo bảng 'images' thành công (nếu chưa tồn tại).")

    except Exception as e:
        # Ghi log lỗi nghiêm trọng này. Ứng dụng có thể không hoạt động nếu DB không được thiết lập đúng cách.
        current_app.logger.critical(f"KHÔNG THỂ KHỞI TẠO CƠ SỞ DỮ LIỆU KHI KHỞI ĐỘNG: {e}", exc_info=True)
        print(f"KHÔNG THỂ KHỞI TẠO CƠ SỞ DỮ LIỆU KHI KHỞI ĐỘNG: {e}") # Log để debug

    finally:
        # Đảm bảo đóng kết nối sau khi sử dụng, ngay cả khi có lỗi
        if conn:
            conn.close()
            print("Đã đóng kết nối init_db.") # Log để debug

with app.app_context():
    init_db()

try:
    # Khởi tạo client Cloud Storage
    storage_client = storage.Client.from_service_account_json("/home/g22028288/upload-image-app/high-theme-456314-a8-1f802896a149.json")
    bucket = storage_client.bucket(BUCKET_NAME)
    print(f"Connected to bucket: {BUCKET_NAME}")  # Thông báo thành công
except Exception as e:
    print(f"Error connecting to bucket: {e}")
    bucket = None  # Đặt bucket thành None nếu kết nối thất bại

@app.route('/test', methods=['GET', 'POST'])
def upload_file():
    if bucket is None:
        return "Error connecting to bucket. Please check logs.", 500  # Trả về lỗi 500 nếu bucket không khả dụng

    if request.method == 'POST':
        if 'file' not in request.files:
            return redirect(request.url)

        file = request.files['file']
        caption = request.form.get('caption', '')
        if file.filename == '':
            return redirect(request.url)

        if file:
            try:
                blob = bucket.blob(file.filename)
                blob.upload_from_file(file)
                return "File uploaded successfully!"
            except Exception as upload_error:
                return f"Error uploading file: {upload_error}", 500

    return render_template('upload.html')


@app.route('/', methods=['GET', 'POST'])
def upload_page():
    if bucket is None:
        app.logger.error("Cloud Storage bucket không khả dụng.")
        return render_template('upload.html', title="Tải lên Hình ảnh"), 503 # Service Unavailable

    if request.method == 'POST':
        if 'file' not in request.files:
            return redirect(request.url)

        file = request.files['file']
        caption = request.form.get('caption', '')
        if file.filename == '':
            return redirect(request.url)

        if file:
            original_filename = secure_filename(file.filename)
            # Tạo tên tệp duy nhất để tránh xung đột
            unique_filename = f"{uuid.uuid4().hex}_{original_filename}"

            try:
                blob = bucket.blob(file.filename)
                blob.upload_from_file(file)
                # Đặt blob ở chế độ công khai có thể đọc (nếu muốn cho thư viện công cộng)
                # Cân nhắc các hàm ý bảo mật. Đối với các tệp riêng tư, quản lý ACL khác nhau.
                blob.make_public()
                public_url = blob.public_url

                #return "File uploaded successfully!" # Đối với một ứng dụng đầy đủ, bạn thường lưu `unique_filename` và `public_url` vào cơ sở dữ liệu tại đây.
                # Sau đó chuyển hướng đến trang thư viện hoặc trang hình ảnh đã tải lên

                cursor = mysql.connection.cursor()
                sql = "INSERT INTO images (filename, gcs_path, public_url, caption) VALUES (%s, %s, %s, %s)"
                cursor.execute(sql, (original_filename, blob.name, public_url, caption))
                mysql.connection.commit()
                
                app.logger.info(f"Đã lưu thông tin tệp {original_filename} vào cơ sở dữ liệu.")
                return redirect(url_for('gallery_page')) # Chuyển hướng đến thư viện sau khi tải lên thành công
            except Exception as upload_error:
                app.logger.error(f"Lỗi khi tải tệp  lên: {upload_error}", exc_info=True)
                return redirect(request.url)

    return render_template('upload.html', title="Tải lên Hình ảnh")

@app.route('/gallery')
def gallery_page():
    images_data = []
    try:
        cursor = mysql.connection.cursor()
        
        cursor.execute("SELECT id, filename, public_url, caption, uploaded_at FROM images ORDER BY uploaded_at DESC")
        images_data = cursor.fetchall()
 
        print(f"Đã truy xuất {len(images_data)} hình ảnh từ cơ sở dữ liệu.")
    except pymysql.MySQLError as db_err:
        app.logger.error(f"Lỗi cơ sở dữ liệu khi tìm nạp hình ảnh: {db_err}")
        flash('Không thể truy xuất hình ảnh từ cơ sở dữ liệu. Vui lòng thử lại.', 'danger')
    except Exception as e:
        app.logger.error(f"Lỗi khi tìm nạp hình ảnh: {e}")
    print(images_data)

    return render_template('gallery.html', title="Thư viện Hình ảnh", images=images_data)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)

