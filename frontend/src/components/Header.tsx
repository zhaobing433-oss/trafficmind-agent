import { useState, useEffect } from 'react';
import { Button, Space } from 'antd';
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons';

interface Props {
  onNewEvent: () => void;
  onRefresh: () => void;
  loading: boolean;
}

export default function Header({ onNewEvent, onRefresh, loading }: Props) {
  const [time, setTime] = useState(new Date());

  useEffect(() => {
    const timer = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  const pad = (n: number) => String(n).padStart(2, '0');
  const timeStr = `${time.getFullYear()}-${pad(time.getMonth() + 1)}-${pad(time.getDate())} ${pad(time.getHours())}:${pad(time.getMinutes())}:${pad(time.getSeconds())}`;

  return (
    <div style={{
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
      padding: '16px 0',
      borderBottom: '1px solid rgba(255,255,255,0.06)',
      marginBottom: 20,
    }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 16 }}>
        <h1 style={{
          margin: 0,
          fontSize: 26,
          fontWeight: 700,
          background: 'linear-gradient(90deg, #4facfe 0%, #00f2fe 100%)',
          WebkitBackgroundClip: 'text',
          WebkitTextFillColor: 'transparent',
          letterSpacing: 2,
        }}>
          🚦 TrafficMind Agent · 智慧交通指挥中心
        </h1>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 20 }}>
        <span style={{
          fontFamily: '"JetBrains Mono", "Fira Code", monospace',
          fontSize: 18,
          color: '#8cb4ff',
          letterSpacing: 1,
        }}>
          {timeStr}
        </span>
        <Space>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={onNewEvent}
            ghost
          >
            新建事件
          </Button>
          <Button
            icon={<ReloadOutlined spin={loading} />}
            onClick={onRefresh}
            ghost
          >
            刷新
          </Button>
        </Space>
      </div>
    </div>
  );
}
