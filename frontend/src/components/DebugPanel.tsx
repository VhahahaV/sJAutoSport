import type { ReactNode } from "react";

type DebugPanelProps = {
  title: string;
  request?: unknown;
  response?: unknown;
  error?: string | null;
  extra?: ReactNode;
};

const formatJSON = (value: unknown) => {
  if (value === undefined) return null;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
};

const DebugPanel = ({ title, request, response, error, extra }: DebugPanelProps) => {
  const requestText = formatJSON(request);
  const responseText = formatJSON(response);
  const hasContent = requestText || responseText || error || extra;

  if (!hasContent) {
    return null;
  }

  return (
    <details className="debug-panel" open={Boolean(error)}>
      <summary>{title}</summary>
      <div className="debug-content">
        {requestText ? (
          <div className="debug-block">
            <div className="debug-label">Request</div>
            <pre>{requestText}</pre>
          </div>
        ) : null}
        {responseText ? (
          <div className="debug-block">
            <div className="debug-label">Response</div>
            <pre>{responseText}</pre>
          </div>
        ) : null}
        {error ? (
          <div className="debug-block">
            <div className="debug-label">Error</div>
            <pre className="debug-error">{error}</pre>
          </div>
        ) : null}
        {extra ? <div className="debug-block">{extra}</div> : null}
      </div>
    </details>
  );
};

export default DebugPanel;
