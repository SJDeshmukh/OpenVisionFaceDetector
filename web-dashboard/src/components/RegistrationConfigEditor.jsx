import React, { useState } from 'react';
import { Plus, Trash2, GripVertical } from 'lucide-react';

const RegistrationConfigEditor = ({ config, onChange }) => {
  // config is an array of objects: { field: '', label: '', type: 'text'|'select', required: boolean, options: [] }

  const addField = () => {
    const newField = {
      field: `field_${Date.now()}`,
      label: 'New Field',
      type: 'text',
      required: false,
      options: []
    };
    onChange([...config, newField]);
  };

  const removeField = (index) => {
    const newConfig = config.filter((_, i) => i !== index);
    onChange(newConfig);
  };

  const updateField = (index, key, value) => {
    const newConfig = [...config];
    newConfig[index] = { ...newConfig[index], [key]: value };
    onChange(newConfig);
  };

  return (
    <div className="bg-slate-50 p-4 rounded-lg border border-slate-200 mt-4">
      <div className="flex justify-between items-center mb-4">
        <h3 className="text-sm uppercase tracking-wide text-slate-500 font-bold">
          Mobile Registration Fields
        </h3>
        <button
          type="button"
          onClick={addField}
          className="text-xs bg-indigo-600 text-white px-2 py-1 rounded hover:bg-indigo-700 flex items-center gap-1"
        >
          <Plus size={14} /> Add Field
        </button>
      </div>

      {config.length === 0 ? (
        <div className="text-center text-slate-400 text-sm py-4 italic">
          No custom fields configured. The mobile app will use default fields only.
        </div>
      ) : (
        <div className="space-y-3">
          {config.map((field, index) => (
            <div key={index} className="bg-white p-3 rounded border border-slate-200 shadow-sm relative group">
              <button
                type="button"
                onClick={() => removeField(index)}
                className="absolute top-2 right-2 text-slate-400 hover:text-red-500 opacity-0 group-hover:opacity-100 transition-opacity"
              >
                <Trash2 size={16} />
              </button>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-3 pr-6">
                <div>
                  <label className="block text-xs font-medium text-slate-500 mb-1">Field ID (Key)</label>
                  <input
                    type="text"
                    value={field.field}
                    onChange={(e) => updateField(index, 'field', e.target.value)}
                    className="w-full p-1.5 text-sm border rounded focus:ring-1 focus:ring-indigo-500 outline-none"
                    placeholder="e.g. employee_id"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-500 mb-1">Display Label</label>
                  <input
                    type="text"
                    value={field.label}
                    onChange={(e) => updateField(index, 'label', e.target.value)}
                    className="w-full p-1.5 text-sm border rounded focus:ring-1 focus:ring-indigo-500 outline-none"
                    placeholder="e.g. Employee ID"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-500 mb-1">Input Type</label>
                  <select
                    value={field.type}
                    onChange={(e) => updateField(index, 'type', e.target.value)}
                    className="w-full p-1.5 text-sm border rounded focus:ring-1 focus:ring-indigo-500 outline-none bg-white"
                  >
                    <option value="text">Text Input</option>
                    <option value="select">Dropdown (Select)</option>
                    <option value="multiselect">Multi-Select</option>
                  </select>
                </div>
                <div className="flex items-center pt-5">
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={field.required}
                      onChange={(e) => updateField(index, 'required', e.target.checked)}
                      className="rounded text-indigo-600 focus:ring-indigo-500"
                    />
                    <span className="text-sm text-slate-600">Required Field</span>
                  </label>
                </div>
              </div>

              {field.type === 'select' && (
                <div className="mt-3 pt-3 border-t border-slate-100">
                  <label className="block text-xs font-medium text-slate-500 mb-1">Dropdown Options (comma separated)</label>
                  <input
                    type="text"
                    value={Array.isArray(field.options) ? field.options.join(', ') : (field.options || '')}
                    onChange={(e) => {
                      const val = e.target.value;
                      // Split by comma, but don't filter empty strings yet so user can type
                      // The final cleaning should happen when we pass the state up or on blur if needed
                      // But for now, we'll just trim each option.
                      updateField(index, 'options', val.split(',').map(s => s.trim()));
                    }}
                    onBlur={(e) => {
                      // On blur, clean up empty options (e.g. if user left a trailing comma)
                      const cleanOptions = field.options.filter(opt => opt.length > 0);
                      updateField(index, 'options', cleanOptions);
                    }}
                    className="w-full p-1.5 text-sm border rounded focus:ring-1 focus:ring-indigo-500 outline-none"
                    placeholder="Option 1, Option 2, Option 3"
                  />
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default RegistrationConfigEditor;
