import { useEffect, useMemo, useState } from "react";

import type { Preset } from "../lib/api";

type PresetSelectorProps = {
  presets: Preset[];
  value: number | "";
  onChange: (presetIndex: number) => void;
  disabled?: boolean;
  onClear?: () => void;
};

type VenueOption = {
  key: string;
  label: string;
  venueName: string;
};

const VENUE_OPTIONS: VenueOption[] = [
  { key: "student-center", label: "学活", venueName: "学生中心" },
  { key: "qimo", label: "气膜", venueName: "气膜体育中心" },
  { key: "zijin", label: "子衿街", venueName: "子衿街学生活动中心" },
  { key: "huo-yingdong", label: "霍英东", venueName: "霍英东体育中心" },
  { key: "nanyang", label: "南洋北苑", venueName: "南洋北苑健身房" },
  { key: "nanqu", label: "南体", venueName: "南区体育馆" },
  { key: "east-tennis", label: "东网", venueName: "东区网球场" },
  { key: "huxiaoming", label: "胡晓明", venueName: "胡晓明网球场" },
];

const PresetSelector = ({ presets, value, onChange, disabled = false, onClear }: PresetSelectorProps) => {
  const [activeVenue, setActiveVenue] = useState<VenueOption | null>(null);

  const presetsByVenue = useMemo(() => {
    const mapping = new Map<string, Preset[]>();
    for (const preset of presets) {
      const venue = VENUE_OPTIONS.find((option) => option.venueName === preset.venue_name);
      if (!venue) continue;
      const existing = mapping.get(venue.key) ?? [];
      mapping.set(venue.key, [...existing, preset]);
    }
    return mapping;
  }, [presets]);

  useEffect(() => {
    if (!value) {
      setActiveVenue(null);
      return;
    }
    const matchedPreset = presets.find((preset) => preset.index === value);
    if (!matchedPreset) {
      setActiveVenue(null);
      return;
    }
    const matchedVenue = VENUE_OPTIONS.find((option) => option.venueName === matchedPreset.venue_name);
    setActiveVenue(matchedVenue ?? null);
  }, [value, presets]);

  const handleVenueClick = (option: VenueOption) => {
    if (disabled) return;
    setActiveVenue(option);
  };

  const handlePresetClick = (presetIndex: number) => {
    if (disabled) return;
    onChange(presetIndex);
  };

  const availableSports = activeVenue ? presetsByVenue.get(activeVenue.key) ?? [] : [];

  return (
    <div className="preset-selector">
      <div className="preset-selector__venue-grid">
        {VENUE_OPTIONS.map((option) => {
          const isDisabled = disabled || (presetsByVenue.get(option.key)?.length ?? 0) === 0;
          const isActive = activeVenue?.key === option.key;
          return (
            <button
              key={option.key}
              type="button"
              className={`preset-selector__button ${isActive ? "is-active" : ""}`}
              onClick={() => handleVenueClick(option)}
              disabled={isDisabled}
            >
              {option.label}
            </button>
          );
        })}
      </div>

      <div className="preset-selector__sports">
        {activeVenue ? (
          availableSports.length > 0 ? (
            availableSports.map((preset) => {
              const isSelected = value === preset.index;
              return (
                <button
                  key={preset.index}
                  type="button"
                  className={`preset-selector__button preset-selector__button--sport ${
                    isSelected ? "is-active" : ""
                  }`}
                  onClick={() => handlePresetClick(preset.index)}
                  disabled={disabled}
                >
                  {preset.field_type_name}
                </button>
              );
            })
          ) : (
            <div className="preset-selector__empty">该场馆暂无可用预设</div>
          )
        ) : (
          <div className="preset-selector__hint">请选择一个场馆以查看可预订的运动项目</div>
        )}
      </div>
      {onClear && value !== "" && (
        <button
          type="button"
          className="preset-selector__clear"
          onClick={onClear}
          disabled={disabled}
        >
          切换为自定义目标
        </button>
      )}
    </div>
  );
};

export default PresetSelector;
