import { useEffect, useState } from "react";

import DebugPanel from "../components/DebugPanel";
import { api, type UserInfoRecord } from "../lib/api";

const sexLabel = (value?: string | null) => {
  if (value === "0") return "男";
  if (value === "1") return "女";
  return value ?? "未知";
};

const UserInfoPage = () => {
  const [records, setRecords] = useState<UserInfoRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastResponse, setLastResponse] = useState<UserInfoRecord[] | null>(null);

  const load = async () => {
    try {
      setLoading(true);
      setError(null);
      const response = await api.getUserInfos();
      setRecords(response.users || []);
      setLastResponse(response.users || []);
    } catch (err) {
      const message = (err as Error).message;
      setError(message);
      setRecords([]);
      setLastResponse(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  return (
    <>
      <div className="content-header">
        <div>
          <h2>用户信息</h2>
          <p style={{ color: "#667085", marginTop: "8px" }}>
            展示当前保存的登录用户信息，数据来自原 CLI `userinfo` 流程。
          </p>
        </div>
        <button className="button button-secondary" type="button" onClick={load} disabled={loading}>
          重新获取
        </button>
      </div>

      {error ? (
        <div className="panel" style={{ border: "1px solid #fca5a5" }}>
          <strong>加载失败</strong>
          <span style={{ color: "#b91c1c" }}>{error}</span>
        </div>
      ) : null}

      <div className="panel" style={{ display: "flex", flexDirection: "column", gap: "18px" }}>
        {loading ? (
          <span style={{ color: "#667085" }}>加载中…</span>
        ) : records.length === 0 ? (
          <span style={{ color: "#667085" }}>暂无用户信息，请先完成登录。</span>
        ) : (
          records.map((record, index) => {
            const profile = record.profile || {};
            return (
              <div
                key={`${record.username || record.nickname || index}`}
                style={{
                  border: "1px solid rgba(148, 163, 184, 0.2)",
                  borderRadius: "12px",
                  padding: "16px",
                  display: "grid",
                  gap: "10px",
                  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
                }}
              >
                <div>
                  <strong>昵称：</strong>
                  {record.nickname || "未命名"}
                </div>
                <div>
                  <strong>用户名：</strong>
                  {record.username || "-"}
                </div>
                <div>
                  <strong>状态：</strong>
                  <span className={`chip ${record.success ? "chip-success" : "chip-warning"}`}>
                    {record.success ? "有效" : "失效"}
                  </span>
                  {record.is_active ? <span style={{ marginLeft: "6px", color: "#2563eb" }}>当前活跃</span> : null}
                </div>
                <div>
                  <strong>姓名：</strong>
                  {profile.user_name || "-"}
                </div>
                <div>
                  <strong>登录名：</strong>
                  {profile.login_name || "-"}
                </div>
                <div>
                  <strong>手机号：</strong>
                  {profile.phone || "-"}
                </div>
                <div>
                  <strong>性别：</strong>
                  {sexLabel(profile.sex)}
                </div>
                <div>
                  <strong>部门：</strong>
                  {profile.dept || "-"}
                </div>
                <div>
                  <strong>学号：</strong>
                  {profile.code || "-"}
                </div>
                <div>
                  <strong>班级：</strong>
                  {profile.class_no || "-"}
                </div>
                <div>
                  <strong>管理员：</strong>
                  {profile.admin ? "是" : "否"}
                </div>
                <div style={{ gridColumn: "1 / -1" }}>
                  <strong>角色：</strong>
                  {profile.roles && profile.roles.length > 0 ? profile.roles.join(" / ") : "无"}
                </div>
                {!record.success && record.message ? (
                  <div style={{ gridColumn: "1 / -1", color: "#b91c1c" }}>
                    错误：{record.message}
                  </div>
                ) : null}
              </div>
            );
          })
        )}
      </div>

      <DebugPanel title="调试信息" response={lastResponse} error={error} />
    </>
  );
};

export default UserInfoPage;
