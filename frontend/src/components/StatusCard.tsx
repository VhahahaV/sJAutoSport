import type { ReactNode } from "react";

type StatusCardProps = {
  title: string;
  value: ReactNode;
  meta?: ReactNode;
};

const StatusCard = ({ title, value, meta }: StatusCardProps) => (
  <div className="card status-card">
    <div className="card-title">{title}</div>
    <div className="card-value">{value}</div>
    {meta ? <div className="card-meta">{meta}</div> : null}
  </div>
);

export default StatusCard;
