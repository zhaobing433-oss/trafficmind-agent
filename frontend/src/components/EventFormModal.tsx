import { useState } from 'react';
import { Modal, Form, Input, InputNumber, Select, Button, Space, message, Spin, Result } from 'antd';
import { analyzeEvent } from '../api';
import type { AnalyzeResult } from '../types';

interface Props {
  open: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

const EVENT_TYPE_OPTIONS = [
  { value: 'congestion', label: '拥堵' },
  { value: 'accident', label: '事故' },
  { value: 'illegal_parking', label: '违停' },
  { value: 'wrong_way', label: '逆行' },
  { value: 'pedestrian_intrusion', label: '行人闯入' },
  { value: 'signal_fault', label: '信号灯异常' },
  { value: 'vehicle_stopped', label: '车辆滞留' },
  { value: 'construction_block', label: '施工占道' },
];

const WEATHER_OPTIONS = [
  { value: 'clear', label: '晴' },
  { value: 'rain', label: '雨' },
  { value: 'snow', label: '雪' },
  { value: 'fog', label: '雾' },
];

const PERIOD_OPTIONS = [
  { value: 'morning_peak', label: '早高峰' },
  { value: 'evening_peak', label: '晚高峰' },
  { value: 'off_peak', label: '平峰' },
];

export default function EventFormModal({ open, onClose, onSuccess }: Props) {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<AnalyzeResult | null>(null);

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();
      setLoading(true);
      const res = await analyzeEvent(values);
      setResult(res);
      message.success('事件分析完成！');
      onSuccess();
    } catch (e) {
      if (e instanceof Error && e.message !== 'VALIDATE_ERROR') {
        message.error(e.message);
      }
    } finally {
      setLoading(false);
    }
  };

  const handleClose = () => {
    form.resetFields();
    setResult(null);
    onClose();
  };

  // 显示分析结果
  if (result) {
    return (
      <Modal
        title="分析结果"
        open={open}
        onCancel={handleClose}
        width={700}
        footer={
          <Space>
            <Button onClick={() => setResult(null)}>继续新建</Button>
            <Button type="primary" onClick={handleClose}>关闭</Button>
          </Space>
        }
      >
        <Result
          status={result.riskLevel === '重大风险' || result.riskLevel === '高风险' ? 'warning' : 'success'}
          title={`风险等级：${result.riskLevel}（${result.riskScore}分）`}
          subTitle={`${result.standardEvent.eventTypeCn} — ${result.standardEvent.roadName}`}
        >
          <div style={{ textAlign: 'left', fontSize: 13, color: 'rgba(255,255,255,0.55)' }}>
            <p><strong>调度话术：</strong></p>
            <pre style={{ whiteSpace: 'pre-wrap', fontSize: 12 }}>{result.dispatchMessage}</pre>
            <p style={{ marginTop: 12 }}><strong>公众提示：</strong>{result.publicMessage}</p>
            <p><strong>保存状态：</strong>{result.saved ? '已保存' : '保存失败'}</p>
          </div>
        </Result>
      </Modal>
    );
  }

  // 输入表单
  return (
    <Modal
      title="新建交通事件分析"
      open={open}
      onCancel={handleClose}
      width={640}
      footer={
        <Space>
          <Button onClick={handleClose}>取消</Button>
          <Button type="primary" loading={loading} onClick={handleSubmit}>
            提交分析
          </Button>
        </Space>
      }
    >
      <Spin spinning={loading}>
        <Form form={form} layout="vertical" size="middle" initialValues={{
          weather: 'clear',
          timePeriod: 'off_peak',
          isMainRoad: true,
          nearbySchool: false,
          nearbyHospital: false,
          confidence: 0.9,
        }}>
          <Form.Item label="事件编号" name="eventId" rules={[{ required: true, message: '请输入事件编号' }]}>
            <Input placeholder="例如 E202606290001" />
          </Form.Item>

          <Form.Item label="事件类型" name="eventType" rules={[{ required: true }]}>
            <Select options={EVENT_TYPE_OPTIONS} placeholder="选择事件类型" />
          </Form.Item>

          <Form.Item label="摄像头 ID" name="cameraId">
            <Input placeholder="例如 CAM_001" />
          </Form.Item>

          <Form.Item label="路段名称" name="roadName" rules={[{ required: true, message: '请输入路段名称' }]}>
            <Input placeholder="例如 人民路-解放路路口" />
          </Form.Item>

          <Space style={{ display: 'flex' }} size={12}>
            <Form.Item label="方向" name="direction" style={{ flex: 1 }}>
              <Input placeholder="东向西" />
            </Form.Item>
            <Form.Item label="车道" name="lane" style={{ flex: 1 }}>
              <Input placeholder="直行车道" />
            </Form.Item>
          </Space>

          <Space style={{ display: 'flex' }} size={12}>
            <Form.Item label="平均车速 (km/h)" name="avgSpeed" rules={[{ required: true }]} style={{ flex: 1 }}>
              <InputNumber min={0} max={200} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item label="排队长度 (米)" name="queueLength" rules={[{ required: true }]} style={{ flex: 1 }}>
              <InputNumber min={0} max={5000} style={{ width: '100%' }} />
            </Form.Item>
          </Space>

          <Space style={{ display: 'flex' }} size={12}>
            <Form.Item label="持续时间 (秒)" name="duration" rules={[{ required: true }]} style={{ flex: 1 }}>
              <InputNumber min={0} max={86400} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item label="涉及车辆" name="vehicleCount" style={{ flex: 1 }}>
              <InputNumber min={0} max={9999} style={{ width: '100%' }} />
            </Form.Item>
          </Space>

          <Space style={{ display: 'flex' }} size={12}>
            <Form.Item label="天气" name="weather" style={{ flex: 1 }}>
              <Select options={WEATHER_OPTIONS} />
            </Form.Item>
            <Form.Item label="时段" name="timePeriod" style={{ flex: 1 }}>
              <Select options={PERIOD_OPTIONS} />
            </Form.Item>
            <Form.Item label="置信度" name="confidence" style={{ flex: 1 }}>
              <InputNumber min={0} max={1} step={0.01} style={{ width: '100%' }} />
            </Form.Item>
          </Space>

          <Space style={{ display: 'flex' }} size={12}>
            <Form.Item label="主干道" name="isMainRoad" valuePropName="checked" style={{ flex: 1 }}>
              <Select options={[{ value: true, label: '是' }, { value: false, label: '否' }]} />
            </Form.Item>
            <Form.Item label="邻近学校" name="nearbySchool" valuePropName="checked" style={{ flex: 1 }}>
              <Select options={[{ value: true, label: '是' }, { value: false, label: '否' }]} />
            </Form.Item>
            <Form.Item label="邻近医院" name="nearbyHospital" valuePropName="checked" style={{ flex: 1 }}>
              <Select options={[{ value: true, label: '是' }, { value: false, label: '否' }]} />
            </Form.Item>
          </Space>
        </Form>
      </Spin>
    </Modal>
  );
}
