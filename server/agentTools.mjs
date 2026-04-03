/** OpenAI-style tool definitions for xAI Grok /v1/chat/completions */
export const AGENT_TOOLS = [
  {
    type: 'function',
    function: {
      name: 'boost_run',
      description:
        'Run Takeoff Boost heuristics on the PDF. scope "page" = current sheet (uses purple AI box if drawn). scope "all" = stub for all pages. Opens the review panel when done.',
      parameters: {
        type: 'object',
        properties: {
          scope: { type: 'string', enum: ['page', 'all'] },
        },
        required: ['scope'],
      },
    },
  },
  {
    type: 'function',
    function: {
      name: 'boost_apply_review',
      description:
        'Approve the current Boost review: add suggested conditions and draw all findings on the canvas. Requires an open Boost review from boost_run.',
      parameters: { type: 'object', properties: {} },
    },
  },
  {
    type: 'function',
    function: {
      name: 'boost_review_add_conditions_only',
      description:
        'From the open Boost review, add only suggested conditions to the project (no marks drawn).',
      parameters: { type: 'object', properties: {} },
    },
  },
  {
    type: 'function',
    function: {
      name: 'boost_dismiss_review',
      description: 'Close the Boost review panel without applying marks.',
      parameters: { type: 'object', properties: {} },
    },
  },
  {
    type: 'function',
    function: {
      name: 'open_boost_dialog',
      description: 'Open the Boost settings dialog so the user can run Boost manually.',
      parameters: { type: 'object', properties: {} },
    },
  },
  {
    type: 'function',
    function: {
      name: 'condition_add',
      description: 'Create a takeoff condition (layer).',
      parameters: {
        type: 'object',
        properties: {
          name: { type: 'string' },
          result_kind: {
            type: 'string',
            enum: [
              'linear',
              'area_gross',
              'area_net',
              'count',
              'assembly',
            ],
          },
          color: { type: 'string', description: '#RRGGBB' },
          line_pattern: {
            type: 'string',
            enum: ['solid', 'dashed', 'dotted', 'dashdot'],
          },
          stroke_width: { type: 'number' },
          fill_opacity: { type: 'number' },
        },
        required: ['name', 'result_kind'],
      },
    },
  },
  {
    type: 'function',
    function: {
      name: 'condition_update',
      description: 'Update an existing condition by id.',
      parameters: {
        type: 'object',
        properties: {
          condition_id: { type: 'string' },
          name: { type: 'string' },
          color: { type: 'string' },
          result_kind: {
            type: 'string',
            enum: [
              'linear',
              'area_gross',
              'area_net',
              'count',
              'assembly',
            ],
          },
          line_pattern: {
            type: 'string',
            enum: ['solid', 'dashed', 'dotted', 'dashdot'],
          },
          stroke_width: { type: 'number' },
          fill_opacity: { type: 'number' },
          apply_to_marks: {
            type: 'string',
            enum: ['none', 'page', 'selection'],
            description:
              'If page or selection, restyle existing marks with this condition.',
          },
        },
        required: ['condition_id'],
      },
    },
  },
  {
    type: 'function',
    function: {
      name: 'condition_remove',
      description: 'Delete a condition by id.',
      parameters: {
        type: 'object',
        properties: { condition_id: { type: 'string' } },
        required: ['condition_id'],
      },
    },
  },
  {
    type: 'function',
    function: {
      name: 'condition_select',
      description: 'Set active drawing conditions (first id is primary style).',
      parameters: {
        type: 'object',
        properties: {
          condition_ids: {
            type: 'array',
            items: { type: 'string' },
          },
        },
        required: ['condition_ids'],
      },
    },
  },
  {
    type: 'function',
    function: {
      name: 'set_current_page',
      description: 'Go to a 1-based sheet number.',
      parameters: {
        type: 'object',
        properties: { page: { type: 'integer' } },
        required: ['page'],
      },
    },
  },
  {
    type: 'function',
    function: {
      name: 'set_takeoff_tool',
      description: 'Change the active drawing or navigation tool.',
      parameters: {
        type: 'object',
        properties: {
          tool: {
            type: 'string',
            enum: [
              'select',
              'pan',
              'ai_scope',
              'line',
              'polyline',
              'polygon',
              'arc',
              'count',
              'measure',
              'text',
            ],
          },
        },
        required: ['tool'],
      },
    },
  },
  {
    type: 'function',
    function: {
      name: 'set_pixels_per_foot',
      description: 'Calibration: pixels per foot for measurements.',
      parameters: {
        type: 'object',
        properties: { value: { type: 'number' } },
        required: ['value'],
      },
    },
  },
  {
    type: 'function',
    function: {
      name: 'set_condition_search',
      description: 'Filter text in the conditions list.',
      parameters: {
        type: 'object',
        properties: { query: { type: 'string' } },
        required: ['query'],
      },
    },
  },
  {
    type: 'function',
    function: {
      name: 'set_active_document',
      description: 'Switch plan PDF by document id (from snapshot documents).',
      parameters: {
        type: 'object',
        properties: { document_id: { type: 'string' } },
        required: ['document_id'],
      },
    },
  },
  {
    type: 'function',
    function: {
      name: 'canvas_undo',
      description: 'Undo last canvas change.',
      parameters: { type: 'object', properties: {} },
    },
  },
  {
    type: 'function',
    function: {
      name: 'canvas_redo',
      description: 'Redo canvas.',
      parameters: { type: 'object', properties: {} },
    },
  },
  {
    type: 'function',
    function: {
      name: 'canvas_delete_selected',
      description: 'Delete selected mark(s) in select tool.',
      parameters: { type: 'object', properties: {} },
    },
  },
  {
    type: 'function',
    function: {
      name: 'canvas_clear_ai_focus',
      description: 'Remove the purple AI focus rectangle from the sheet.',
      parameters: { type: 'object', properties: {} },
    },
  },
  {
    type: 'function',
    function: {
      name: 'highlight_mark',
      description: 'Select a mark on canvas by nid.',
      parameters: {
        type: 'object',
        properties: { mark_nid: { type: 'string' } },
        required: ['mark_nid'],
      },
    },
  },
  {
    type: 'function',
    function: {
      name: 'toggle_left_sidebar',
      description: 'Collapse/expand left project sidebar.',
      parameters: { type: 'object', properties: {} },
    },
  },
  {
    type: 'function',
    function: {
      name: 'toggle_right_sidebar',
      description: 'Collapse/expand right properties sidebar.',
      parameters: { type: 'object', properties: {} },
    },
  },
  {
    type: 'function',
    function: {
      name: 'set_boost_review_panel_open',
      description: 'Open or close the bottom Boost review strip (if review exists).',
      parameters: {
        type: 'object',
        properties: { open: { type: 'boolean' } },
        required: ['open'],
      },
    },
  },
  {
    type: 'function',
    function: {
      name: 'project_save_local',
      description: 'Save project to browser IndexedDB.',
      parameters: { type: 'object', properties: {} },
    },
  },
  {
    type: 'function',
    function: {
      name: 'navigate_to_projects_screen',
      description: 'Leave workspace and open the projects list.',
      parameters: { type: 'object', properties: {} },
    },
  },
];
