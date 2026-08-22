import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import cv2

print("=" * 60)
print("🎥 ทดสอบแสดงกล้องแบบง่าย")
print("=" * 60)

cap = cv2.VideoCapture(0)

if not cap.isOpened():
    print("❌ ไม่สามารถเปิดกล้องได้")
    exit()

print("✅ เปิดกล้องสำเร็จ")
print("💡 กด 'q' เพื่อออก\n")

cv2.namedWindow('Camera Test', cv2.WINDOW_NORMAL)
cv2.resizeWindow('Camera Test', 800, 600)

frame_count = 0
try:
    while True:
        ret, frame = cap.read()
        if not ret:
            print("❌ ไม่สามารถอ่าน frame")
            break
        
        frame_count += 1
        
        # เพิ่มตัวนับ frame บนหน้าจอ
        cv2.putText(frame, f"Frame: {frame_count}", (10, 30), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        
        cv2.imshow('Camera Test', frame)
        
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            print("\n✅ ปิดโปรแกรม")
            break
        
        if frame_count % 30 == 0:
            print(f"📹 กำลังอ่าน frame {frame_count}...")

except KeyboardInterrupt:
    print("\n🛑 ถูก interrupt")

finally:
    print("🔒 ปิดกล้อง...")
    cap.release()
    cv2.destroyAllWindows()
    print("✔️ เสร็จสิ้น")
