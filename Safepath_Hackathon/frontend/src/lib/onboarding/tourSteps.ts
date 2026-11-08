import type { DriveStep } from "driver.js";

export type TourState = {
  version: "v1";
  status: "completed" | "skipped" | "in_progress" | "idle";
  lastStepId?: string;
  updatedAt: string;
};

export const INITIAL_TOUR_STATE: TourState = {
  version: "v1",
  status: "idle",
  updatedAt: new Date().toISOString(),
};

/**
 * 6-step Map Tour on /map
 */
export const MAP_TOUR_STEPS: DriveStep[] = [
  {
    element: '[data-testid="origin-combobox"]',
    popover: {
      title: "Bước 1: Chọn điểm xuất phát",
      description:
        "Nhập địa chỉ, tên đường hoặc bấm biểu tượng Định vị để tự động lấy vị trí hiện tại của bạn.",
      side: "right",
      align: "start",
    },
  },
  {
    element: '[data-testid="destination-combobox"]',
    popover: {
      title: "Bước 2: Chọn điểm đến",
      description:
        "Nhập nơi bạn muốn đến hoặc bấm biểu tượng Ghim để chọn vị trí trực tiếp trên bản đồ TP.HCM.",
      side: "right",
      align: "start",
    },
  },
  {
    element: '[data-tour="search-route-btn"]',
    popover: {
      title: "Bước 3: Tìm tuyến đường an toàn",
      description:
        "SafePathAI sẽ tính toán lộ trình tối ưu, tự động tránh các điểm ngập nước và phân tích lưu thông theo thời gian thực.",
      side: "bottom",
      align: "center",
    },
  },
  {
    element: '[data-tour="camera-toggle"]',
    popover: {
      title: "Bước 4: Camera giao thông thực tế",
      description:
        "Bật / tắt hiển thị mạng lưới 796 camera giao thông. Bạn có thể lọc riêng các camera có ảnh hoặc camera nằm trên tuyến di chuyển.",
      side: "left",
      align: "center",
    },
  },
  {
    element: '[data-tour="nav-guidance"]',
    popover: {
      title: "Bước 5: Hướng dẫn di chuyển & Cảnh báo",
      description:
        "Xem hướng dẫn từng ngã rẽ và bật trợ lý giọng nói tiếng Việt để nhận cảnh báo khi gần đến khu vực trũng ngập.",
      side: "right",
      align: "start",
    },
  },
  {
    element: '[data-tour="nav-news-link"]',
    popover: {
      title: "Bước 6: Bản tin giao thông đô thị",
      description:
        "Đọc những cập nhật mới nhất về ùn tắc, ngập lụt và thi công công trình tại TP.HCM trước khi ra đường.",
      side: "bottom",
      align: "center",
    },
  },
];

/**
 * 5-step Traffic News Tour on /news
 */
export const NEWS_TOUR_STEPS: DriveStep[] = [
  {
    element: '[data-tour="news-hero"]',
    popover: {
      title: "1. Tiêu điểm giao thông TP.HCM",
      description:
        "Cập nhật sự cố nổi bật nhất trong ngày từ các nguồn báo chí uy tín (VnExpress, Tuổi Trẻ, Cổng GTVT).",
      side: "bottom",
      align: "start",
    },
  },
  {
    element: '[data-tour="news-highlights"]',
    popover: {
      title: "2. Tình hình đáng chú ý",
      description:
        "Các sự cố giao thông, tai nạn, điểm thi công rào chắn ảnh hưởng trực tiếp đến việc lưu thông của bạn.",
      side: "bottom",
      align: "center",
    },
  },
  {
    element: '[data-tour="news-filters"]',
    popover: {
      title: "3. Bộ lọc sự cố & Khám phá khu vực",
      description:
        "Dễ dàng lọc theo ngập nước, ùn tắc, tai nạn, mốc thời gian hoặc chọn riêng từng quận / huyện bạn cần theo dõi.",
      side: "bottom",
      align: "center",
    },
  },
  {
    element: '[data-tour="news-bookmark-action"]',
    popover: {
      title: "Lưu tin tức quan trọng",
      description:
        "Bấm biểu tượng dấu trang bên cạnh bài viết để lưu tin bạn quan tâm. Bạn có thể xem lại các bài đã lưu bất cứ lúc nào trong Bản tin.",
      side: "top",
      align: "center",
    },
  },
];

