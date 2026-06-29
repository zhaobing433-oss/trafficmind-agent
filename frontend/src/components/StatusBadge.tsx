import { Tag } from 'antd';
import { statusColor } from '../utils/format';

interface Props {
  status: string;
}

export default function StatusBadge({ status }: Props) {
  return (
    <Tag color={statusColor(status)} bordered={false}>
      {status}
    </Tag>
  );
}
