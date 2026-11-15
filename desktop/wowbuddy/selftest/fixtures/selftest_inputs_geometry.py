"""0737EA–0742D7 原始常量与构图；不依赖外部证据文件。"""
from copy import deepcopy
import struct

METADATA = {'schema': 'wowbuddy-native-geometry-selftest-v1',
 'source_kind': 'static-native-instructions-and-PE-constants',
 'original_sha256': '7b3c05fdbc2369f7a8fb7bb870fb0341ba1891223212e3a02b54d5c62fb9d488',
 'entry_function_va': '0x140062cd0',
 'group_range_va': ['0x1400737ea', '0x1400742d7'],
 'sample_count': 183,
 'case_count': 6,
 'fpu_assumption': 'FE_TONEAREST; nearbyint ties-to-even; original process not executed by extraction',
 'report_templates': {'header': {'va': '0x1400d8860',
                                 'utf16_units': 37,
                                 'text': '\n\n== 像素条几何（capture.cpp refinePitch）=='},
                      'no_marker': {'va': '0x1400d88b0', 'utf16_units': 15, 'text': '  ✗ 缩放 %1：没找到基准'},
                      'case': {'va': '0x1400d88d0',
                               'utf16_units': 49,
                               'text': '  %1 缩放 %2：粗 pitch %3 → 锁定 %4（真值 %5），读错 %6/%7 行%8'},
                      'first_wrong': {'va': '0x1400d8938', 'utf16_units': 11, 'text': '（首个在第 %1 行）'},
                      'summary': {'va': '0x1400d8950',
                                  'utf16_units': 59,
                                  'text': '  小结：%1/%2 组缩放全 183 行逐格读对 —— 旧读法在 1.2 那一组会把第 158、183 行读进隔壁格'},
                      'failure_warning': {'va': '0x1400d89c8',
                                          'utf16_units': 26,
                                          'text': '  ★ 有用例失败：条子几何已跑偏，别发这套 EXE'},
                      'pass_symbol': {'va': '0x1400d5bd0', 'utf16_units': 1, 'text': '✓'},
                      'fail_symbol': {'va': '0x1400d5bd4', 'utf16_units': 1, 'text': '✗'}},
 'constants': {'scales': {'va': '0x1400d98d0',
                          'bytes_le': '000000000000f03f000000000000f23f333333333333f33f000000000000f43fda1b7c613255f53f0000000000000040'},
               'double_pool': {'cell_size': {'va': '0x1400d1c98',
                                             'value': 4.0,
                                             'bytes_le': '0000000000001040'},
                               'height_base': {'va': '0x1400d9870',
                                               'value': 732.0,
                                               'bytes_le': '0000000000e08640'},
                               'marker_y0': {'va': '0x1400d9860',
                                             'value': 128.0,
                                             'bytes_le': '0000000000006040'},
                               'marker_y1': {'va': '0x1400d9868',
                                             'value': 132.0,
                                             'bytes_le': '0000000000806040'},
                               'marker_x1': {'va': '0x1400d33f8',
                                             'value': 8.0,
                                             'bytes_le': '0000000000002040'},
                               'sample_center_factor': {'va': '0x1400d1c88',
                                                        'value': 0.5,
                                                        'bytes_le': '000000000000e03f'}},
               'palette_argb': [4278255360, 4281545523, 4294901760],
               'marker_argb': 4294902015,
               'background_argb': 4279045389},
 'construction': {'image_width': 24,
                  'image_height': 'nearbyint(732.0 * scale) + 16',
                  'qimage_format': 4,
                  'cell_width': 'max(1, nearbyint(4.0 * scale))',
                  'cell_y_bounds': '[nearbyint((float(i)*4.0)*scale), nearbyint((float(i+1)*4.0)*scale))',
                  'palette_index': '(3 + 7*i) % 3',
                  'marker_rect': '[nearbyint(4*scale), nearbyint(128*scale), nearbyint(8*scale), '
                                 'nearbyint(132*scale))',
                  'write_order': ['QImage constructor', 'fill background', '183 cells', 'magenta marker']},
 'native_assertion': {'sample_call_va': '0x140073c54',
                      'compare_loop_va': ['0x140073c83', '0x140073cb0'],
                      'comparison': 'full uint32 ARGB equality; not color-distance comparison',
                      'short_array': 'each missing expected index counts wrong',
                      'extra_samples': 'ignored',
                      'first_wrong_index_internal': 'zero based, initial -1',
                      'first_wrong_index_report': 'internal+1',
                      'pass_condition': 'marker valid AND wrong_rows==0',
                      'pitch_equality_assertion': False,
                      'diagnostic_refine_x': 'clamp(nearbyint(origin_x+cell_width*0.5),0,23)',
                      'diagnostic_refine_count': 183,
                      'no_marker': 'log no_marker, destroy current vector/image, continue next scale, no '
                                   'pass increment',
                      'summary_warning_if': 'pass_count != 6',
                      'function_normal_return_value': 0,
                      'function_return_evidence_va': '0x140074455'},
 'helpers': {'0x140060270': 'qRgb-like pack: 0xFF000000 | ((r & 255)<<16) | (g<<8) | b; invoked with13,13,13 '
                            'at0738eb',
             '0x140056f50': 'allocate183 uint32 values and zero-initialize expected array',
             '0x1400577a0': 'detach expected QVector if needed and return data+i*4',
             '0x14001e4b0': 'integer clamp helper; receives0,rounded center,23',
             '0x140054cf0': 'QString::arg_impl wrapper; report specifies f/4 for scale, f/5 for pitches; '
                            'no-marker specifies g/-1'},
 'evidence': {'assembly_path': '../native-listing/main-all-executable-sections.asm',
              'assembly_sha256': '115efc8c5d6bc3d139e90082d3606314763a94651d9de57c1be402c9674de4c7',
              'draw_va': ['0x14007388a', '0x140073b3d'],
              'locate_call_va': '0x140073b3d',
              'refine_diagnostic_call_va': '0x140073d19',
              'summary_va': ['0x1400741be', '0x1400742d7'],
              'scales_loop_end_va': '0x1400741ad'}}


def build_geometry_inputs():
    result = deepcopy(METADATA)
    raw = bytes.fromhex(result['constants']['scales']['bytes_le'])
    palette = result['constants']['palette_argb']
    cases = []
    for n, (scale,) in enumerate(struct.iter_unpack('<d', raw)):
        colors = [palette[(3 + 7*i) % 3] for i in range(183)]
        cases.append(dict(
            id=f'geometry-scale-{n+1}', scale=scale,
            scale_ieee754_le=raw[n*8:n*8+8].hex(), scale_va=hex(0x1400D98D0+n*8),
            image=dict(width=24, height=round(732.0*scale)+16, format=4,
                       fill_argb=result['constants']['background_argb']),
            cells=[dict(row=i, rect=[0,round((float(i)*4.0)*scale),
                max(1,round(4.0*scale)),round((float(i+1)*4.0)*scale)],argb=color)
                for i,color in enumerate(colors)],
            marker=dict(rect=[round(4.0*scale),round(128.0*scale),
                round(8.0*scale),round(132.0*scale)],argb=result['constants']['marker_argb']),
            expected_argb=colors))
    result['cases'] = cases
    return result
