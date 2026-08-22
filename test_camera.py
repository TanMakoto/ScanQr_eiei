import cv2
import sys

print("=" * 60)
print("🔍 ทดสอบการเชื่อมต่อกล้อง")
print("=" * 60)

# ตรวจสอบเวอร์ชัน OpenCV
print(f"\n📦 OpenCV Version: {cv2.__version__}")
print(f"🐍 Python Version: {sys.version}")

# ลองเปิดกล้องจาก index 0-10
print("\n🔎 กำลังค้นหากล้อง...\n")

camera_found = False
for idx in range(10):
    print(f"  ทดสอบ index {idx}...", end=" ")
    cap = cv2.VideoCapture(idx)
    
    if not cap.isOpened():
        print("❌ ไม่สามารถเปิด")
        cap.release()
        continue
    
    # ตรวจสอบว่า frame loader ได้หรือไม่
    ret, frame = cap.read()
    if ret and frame is not None:
        h, w = frame.shape[:2]
        print(f"✅ สำเร็จ! ความละเอียด: {w}x{h}")
        camera_found = True
        cap.release()
        break
    else:
        print("❌ ไม่สามารถอ่าน frame")
        cap.release()

print("\n" + "=" * 60)
if camera_found:
    print("✅ พบกล้องที่ index:", idx)
    print("แนะนำ: ใช้ cv2.VideoCapture(" + str(idx) + ") ในโค้ด")
else:
    print("❌ ไม่พบกล้องใดเลย")
    print("\n💡 วิธีแก้:")
    print("  1. ตรวจสอบว่าเชื่อมต่อกล้องหรือไม่")
    print("  2. ลองเปลี่ยน USB port")
    print("  3. ตรวจสอบว่า drivers ของกล้องติดตั้งแล้วไหม")
    print("  4. ปิดโปรแกรมอื่นที่ใช้กล้องอยู่")

print("=" * 60)
