/**
 * ThinkingAvatar — 回答生成期间的动态头像
 * 需要把 bot_1.png ~ bot_4.png 放到 frontend/public 目录
 * 图片不存在时降级为静态圆形图标
 */
import { useState, useEffect } from 'react';
import { RobotOutlined } from '@ant-design/icons';

const FRAMES = ['/bot_1.png', '/bot_2.png', '/bot_3.png', '/bot_4.png'];

export default function ThinkingAvatar() {
  const [index, setIndex] = useState(0);
  const [hasImages, setHasImages] = useState<boolean | null>(null);

  useEffect(() => {
    // Check if images exist
    const img = new Image();
    img.onload = () => setHasImages(true);
    img.onerror = () => setHasImages(false);
    img.src = FRAMES[0];
  }, []);

  useEffect(() => {
    if (!hasImages) return;
    const timer = setInterval(() => setIndex(i => (i + 1) % FRAMES.length), 400);
    return () => clearInterval(timer);
  }, [hasImages]);

  if (hasImages === null) {
    return (
      <div style={{ width: 36, height: 36, borderRadius: 18, background: '#F0FDFA', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <RobotOutlined style={{ color: '#0F766E' }} />
      </div>
    );
  }

  if (!hasImages) {
    return (
      <div style={{ width: 36, height: 36, borderRadius: 18, background: '#F0FDFA', display: 'flex', alignItems: 'center', justifyContent: 'center', animation: 'pulse 1.5s ease-in-out infinite' }}>
        <RobotOutlined style={{ color: '#0F766E', fontSize: 16 }} />
      </div>
    );
  }

  return (
    <img src={FRAMES[index]} alt="thinking"
      style={{ width: 36, height: 36, borderRadius: 18, objectFit: 'cover' }}
    />
  );
}
