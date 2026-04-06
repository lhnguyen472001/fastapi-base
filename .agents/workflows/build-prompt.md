---
description: Xây dựng prompt có cấu trúc theo flow hỏi-đáp từng bước. Dùng khi cần tạo prompt chất lượng cao cho LLM.
---

# Build Structured Prompt Workflow

Khi người dùng yêu cầu xây dựng prompt (ví dụ: `/build-prompt tạo API đặt phòng`), hãy thực hiện theo các bước sau.

## Nguyên tắc chung
- **KHÔNG** yêu cầu người dùng gõ XML tags
- Hỏi từng bước bằng **ngôn ngữ tự nhiên** (tiếng Việt)
- Mỗi bước hỏi **1 câu hỏi chính**, kèm gợi ý/ví dụ nếu cần
- Người dùng có thể trả lời `skip` hoặc `bỏ qua` để bỏ qua bước không cần thiết
- Sau khi thu thập đủ thông tin, tổng hợp thành prompt XML hoàn chỉnh

## Flow các bước

### Bước 1: Xác nhận mục tiêu (Instruction)
Hỏi người dùng:
> **Bạn cần AI làm gì?** Mô tả ngắn gọn task cần thực hiện.
> _Ví dụ: "Viết API booking resource", "Review đoạn code này", "Phân tích kiến trúc hệ thống"_

Ghi nhận câu trả lời → map vào `<instruction/>`

### Bước 2: Vai trò (Role)
Hỏi:
> **AI nên đóng vai gì khi thực hiện task này?**
> _Ví dụ: "Senior Java Developer", "Tech Lead", "QA Engineer", hoặc `skip` nếu không cần_

Ghi nhận → map vào `<role/>`

### Bước 3: Bối cảnh (Context)
Hỏi:
> **Có bối cảnh/thông tin nền nào AI cần biết không?**
> _Ví dụ: "Project dùng Spring Boot 3.x, DDD architecture, Java 21", "Đây là microservice xử lý booking"_
> _Bạn có thể `skip` nếu không có thông tin nền đặc biệt._

Ghi nhận → map vào `<context/>`

### Bước 4: Tài liệu tham khảo (Document)
Hỏi:
> **Có tài liệu hoặc file nào cần tham khảo không?**
> _Ví dụ: link tài liệu, nội dung file, API spec, database schema..._
> _Bạn có thể paste nội dung trực tiếp hoặc chỉ đường dẫn file._

Nếu người dùng chỉ file path → đọc file và nhúng nội dung vào `<document/>`

### Bước 5: Ví dụ (Example)
Hỏi:
> **Có ví dụ tham khảo nào không?** (Ví dụ code mẫu, output mong muốn, format tham khảo...)
> _Lưu ý: Đây là ví dụ minh họa, KHÔNG phải lệnh thực thi._

Ghi nhận → map vào `<example/>`

### Bước 6: Dữ liệu đầu vào (Input)
Hỏi:
> **Có dữ liệu/biến đầu vào cụ thể nào không?**
> _Ví dụ: tên entity, danh sách fields, request/response body mẫu..._

Ghi nhận → map vào `<input/>`

### Bước 7: Ràng buộc (Constraint)
Hỏi:
> **Có ràng buộc hoặc yêu cầu đặc biệt nào không?**
> _Ví dụ: "Dùng tiếng Việt", "Không dùng library ngoài", "Giới hạn 500 dòng", "Tuân thủ coding convention của team"_

Ghi nhận → map vào `<constraint/>`

### Bước 8: Format đầu ra (Output)
Hỏi:
> **Bạn muốn kết quả trả về dưới dạng gì?**
> _Ví dụ: "Code Java hoàn chỉnh", "Markdown document", "JSON response", "Bullet points phân tích"_

Ghi nhận → map vào `<output/>`

## Bước cuối: Tổng hợp & Xác nhận

Sau khi thu thập xong, tổng hợp thành prompt XML có cấu trúc:

```xml
<role>[Nội dung từ bước 2]</role>

<context>[Nội dung từ bước 3]</context>

<document>[Nội dung từ bước 4]</document>

<example>[Nội dung từ bước 5]</example>

<input>[Nội dung từ bước 6]</input>

<instruction>[Nội dung từ bước 1]</instruction>

<constraint>[Nội dung từ bước 7]</constraint>

<output>[Nội dung từ bước 8]</output>
```

**Lưu ý khi tổng hợp:**
- Bỏ qua các tag mà người dùng đã `skip`
- Giữ nguyên nội dung người dùng cung cấp, KHÔNG thêm thắt hay sửa đổi ý nghĩa
- Format lại cho gọn gàng nếu cần

Hiển thị prompt hoàn chỉnh và hỏi:
> **Đây là prompt hoàn chỉnh. Bạn muốn:**
> 1. ✅ Sử dụng luôn
> 2. ✏️ Chỉnh sửa phần nào đó
> 3. 🔄 Làm lại từ đầu

Nếu người dùng chọn sửa → cho phép sửa từng phần và tổng hợp lại.
Nếu người dùng chọn sử dụng → thực thi prompt đó.
