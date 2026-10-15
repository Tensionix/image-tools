# Audion Build Licenses Scan Report

- Project: **Audion Image Tools** (`audion-image-tools`)
- Run: `20261015T233554Z_audion-image-tools_95f4fea7`
- Scan root (from the project root): `.`
- Output (from the project root): `licenses`
- Status: **REVIEW**
- Components: 112
- Bundled: 112
- Optional runtime: 0

## Issues

| Severity | Code | Component/path | Message |
|---|---|---|---|
| REVIEW | `COPYLEFT_LINKED_INTO_PROGRAM` | pymupdf | pymupdf is under GPL-3.0 and runs inside the program (python_import). The program as a whole is then distributed under the GPL: its complete source has to be offered. Decide whether that is intended, or run the component as a separate program. The licence of pymupdf was made out from a descriptive line ("Dual Licensed - GNU AFFERO GPL 3.0 or Artifex Commercial License"), not from an exact expression: check what the installed files are really under, and state it in a profile. |

## Changes since previous scan

| Component | Change | Old | New |
|---|---|---:|---:|
| Audion launcher | `UNCHANGED` | bundled | bundled |
| Avalonia | `UNCHANGED` | 12.1.4 | 12.1.4 |
| Avalonia.Angle.Windows.Natives | `UNCHANGED` | 2.1.27548.20260419 | 2.1.27548.20260419 |
| Avalonia.Desktop | `UNCHANGED` | 12.1.4 | 12.1.4 |
| Avalonia.Fonts.Inter | `UNCHANGED` | 12.1.4 | 12.1.4 |
| Avalonia.FreeDesktop | `UNCHANGED` | 12.1.4 | 12.1.4 |
| Avalonia.FreeDesktop.AtSpi | `UNCHANGED` | 12.1.4 | 12.1.4 |
| Avalonia.HarfBuzz | `UNCHANGED` | 12.1.4 | 12.1.4 |
| Avalonia.Native | `UNCHANGED` | 12.1.4 | 12.1.4 |
| Avalonia.Remote.Protocol | `UNCHANGED` | 12.1.4 | 12.1.4 |
| Avalonia.Skia | `UNCHANGED` | 12.1.4 | 12.1.4 |
| Avalonia.Themes.Fluent | `UNCHANGED` | 12.1.4 | 12.1.4 |
| Avalonia.Win32 | `UNCHANGED` | 12.1.4 | 12.1.4 |
| Avalonia.X11 | `UNCHANGED` | 12.1.4 | 12.1.4 |
| build | `VERSION_OR_ARTIFACT_CHANGED_LICENSE_SAME` | 1.6.1 | 1.6.1 |
| click | `VERSION_OR_ARTIFACT_CHANGED_LICENSE_SAME` | 8.5.0 | 8.5.0 |
| colorama | `VERSION_OR_ARTIFACT_CHANGED_LICENSE_SAME` | 0.4.6 | 0.4.6 |
| HarfBuzzSharp | `UNCHANGED` | 8.3.1.3 | 8.3.1.3 |
| HarfBuzzSharp.NativeAssets.Win32 | `UNCHANGED` | 8.3.1.3 | 8.3.1.3 |
| Humanizer.Core | `UNCHANGED` | 2.14.1 | 2.14.1 |
| img2pdf | `VERSION_OR_ARTIFACT_CHANGED_LICENSE_SAME` | 0.6.3 | 0.6.3 |
| iniconfig | `VERSION_OR_ARTIFACT_CHANGED_LICENSE_SAME` | 2.3.1 | 2.3.1 |
| Inter | `UNCHANGED` | 3.019 | 3.019 |
| JetBrains Mono | `UNCHANGED` | 2.211 | 2.211 |
| Json.More.Net | `UNCHANGED` | 2.1.1 | 2.1.1 |
| JsonPointer.Net | `UNCHANGED` | 5.3.1 | 5.3.1 |
| JsonSchema.Net | `UNCHANGED` | 7.4.0 | 7.4.0 |
| Lucide | `UNCHANGED` | 1.48.0 | 1.48.0 |
| lxml | `VERSION_OR_ARTIFACT_CHANGED_LICENSE_SAME` | 6.1.3 | 6.1.3 |
| Markdig.Signed | `UNCHANGED` | 0.44.0 | 0.44.0 |
| MicroCom.Runtime | `UNCHANGED` | 0.11.6 | 0.11.6 |
| Microsoft.ApplicationInsights | `UNCHANGED` | 2.23.0 | 2.23.0 |
| Microsoft.Bcl.AsyncInterfaces | `UNCHANGED` | 10.0.5 | 10.0.5 |
| Microsoft.CodeAnalysis.Common | `UNCHANGED` | 5.0.0 | 5.0.0 |
| Microsoft.CodeAnalysis.CSharp | `UNCHANGED` | 5.0.0 | 5.0.0 |
| Microsoft.Extensions.ObjectPool | `UNCHANGED` | 10.0.5 | 10.0.5 |
| Microsoft.Management.Infrastructure | `UNCHANGED` | 3.0.0 | 3.0.0 |
| Microsoft.Management.Infrastructure.CimCmdlets | `UNCHANGED` | 7.6.7 | 7.6.7 |
| Microsoft.Management.Infrastructure.Runtime.Win | `UNCHANGED` | 3.0.0 | 3.0.0 |
| Microsoft.NETCore.App.Runtime.win-x64 | `UNCHANGED` | 10.0.13 | 10.0.13 |
| Microsoft.PowerShell.Commands.Diagnostics | `UNCHANGED` | 7.6.7 | 7.6.7 |
| Microsoft.PowerShell.Commands.Management | `UNCHANGED` | 7.6.7 | 7.6.7 |
| Microsoft.PowerShell.Commands.Utility | `UNCHANGED` | 7.6.7 | 7.6.7 |
| Microsoft.PowerShell.ConsoleHost | `UNCHANGED` | 7.6.7 | 7.6.7 |
| Microsoft.PowerShell.CoreCLR.Eventing | `UNCHANGED` | 7.6.7 | 7.6.7 |
| Microsoft.PowerShell.MarkdownRender | `UNCHANGED` | 7.2.1 | 7.2.1 |
| Microsoft.PowerShell.Native | `UNCHANGED` | 700.0.2 | 700.0.2 |
| Microsoft.PowerShell.SDK | `UNCHANGED` | 7.6.7 | 7.6.7 |
| Microsoft.PowerShell.Security | `UNCHANGED` | 7.6.7 | 7.6.7 |
| Microsoft.Security.Extensions | `UNCHANGED` | 1.4.0 | 1.4.0 |
| Microsoft.Win32.Registry.AccessControl | `UNCHANGED` | 10.0.5 | 10.0.5 |
| Microsoft.Win32.SystemEvents | `UNCHANGED` | 10.0.5 | 10.0.5 |
| Microsoft.Windows.Compatibility | `UNCHANGED` | 10.0.5 | 10.0.5 |
| Microsoft.WSMan.Management | `UNCHANGED` | 7.6.7 | 7.6.7 |
| Microsoft.WSMan.Runtime | `UNCHANGED` | 7.6.7 | 7.6.7 |
| Newtonsoft.Json | `UNCHANGED` | 13.0.4 | 13.0.4 |
| numpy | `VERSION_OR_ARTIFACT_CHANGED_LICENSE_SAME` | 2.5.4 | 2.5.4 |
| packaging | `VERSION_OR_ARTIFACT_CHANGED_LICENSE_SAME` | 26.3 | 26.3 |
| pikepdf | `VERSION_OR_ARTIFACT_CHANGED_LICENSE_SAME` | 10.17.0 | 10.17.0 |
| pillow | `VERSION_OR_ARTIFACT_CHANGED_LICENSE_SAME` | 12.3.0 | 12.3.0 |
| pillow_heif | `VERSION_OR_ARTIFACT_CHANGED_LICENSE_SAME` | 1.8.1 | 1.8.1 |
| pip | `VERSION_OR_ARTIFACT_CHANGED_LICENSE_SAME` | 26.2.1 | 26.2.1 |
| pip-tools | `VERSION_OR_ARTIFACT_CHANGED_LICENSE_SAME` | 7.6.2 | 7.6.2 |
| pluggy | `VERSION_OR_ARTIFACT_CHANGED_LICENSE_SAME` | 1.7.0 | 1.7.0 |
| Pygments | `VERSION_OR_ARTIFACT_CHANGED_LICENSE_SAME` | 2.21.0 | 2.21.0 |
| pymupdf | `VERSION_OR_ARTIFACT_CHANGED_LICENSE_SAME` | 1.28.2 | 1.28.2 |
| pyproject_hooks | `VERSION_OR_ARTIFACT_CHANGED_LICENSE_SAME` | 1.3.3 | 1.3.3 |
| pytest | `VERSION_OR_ARTIFACT_CHANGED_LICENSE_SAME` | 9.1.1 | 9.1.1 |
| Python Embedded | `VERSION_OR_ARTIFACT_CHANGED_LICENSE_SAME` | 3.12.x | 3.12.x |
| PyYAML | `VERSION_OR_ARTIFACT_CHANGED_LICENSE_SAME` | 6.0.3 | 6.0.3 |
| rawpy | `VERSION_OR_ARTIFACT_CHANGED_LICENSE_SAME` | 0.27.1 | 0.27.1 |
| runtime.native.System.Data.SqlClient.sni | `UNCHANGED` | 4.4.0 | 4.4.0 |
| runtime.win-x64.runtime.native.System.Data.SqlClient.sni | `UNCHANGED` | 4.4.0 | 4.4.0 |
| setuptools | `VERSION_OR_ARTIFACT_CHANGED_LICENSE_SAME` | 84.0.0 | 84.0.0 |
| SkiaSharp | `UNCHANGED` | 3.119.4 | 3.119.4 |
| SkiaSharp.NativeAssets.Win32 | `UNCHANGED` | 3.119.4 | 3.119.4 |
| System.CodeDom | `UNCHANGED` | 10.0.5 | 10.0.5 |
| System.ComponentModel.Composition | `UNCHANGED` | 10.0.5 | 10.0.5 |
| System.ComponentModel.Composition.Registration | `UNCHANGED` | 10.0.5 | 10.0.5 |
| System.Configuration.ConfigurationManager | `UNCHANGED` | 10.0.5 | 10.0.5 |
| System.Data.Odbc | `UNCHANGED` | 10.0.5 | 10.0.5 |
| System.Data.OleDb | `UNCHANGED` | 10.0.5 | 10.0.5 |
| System.Data.SqlClient | `UNCHANGED` | 4.9.1 | 4.9.1 |
| System.Diagnostics.EventLog | `UNCHANGED` | 10.0.5 | 10.0.5 |
| System.Diagnostics.PerformanceCounter | `UNCHANGED` | 10.0.5 | 10.0.5 |
| System.DirectoryServices | `UNCHANGED` | 10.0.5 | 10.0.5 |
| System.DirectoryServices.AccountManagement | `UNCHANGED` | 10.0.5 | 10.0.5 |
| System.DirectoryServices.Protocols | `UNCHANGED` | 10.0.5 | 10.0.5 |
| System.Drawing.Common | `UNCHANGED` | 10.0.5 | 10.0.5 |
| System.IO.Packaging | `UNCHANGED` | 10.0.5 | 10.0.5 |
| System.IO.Ports | `UNCHANGED` | 10.0.5 | 10.0.5 |
| System.Management | `UNCHANGED` | 10.0.5 | 10.0.5 |
| System.Management.Automation | `UNCHANGED` | 7.6.7 | 7.6.7 |
| System.Net.Http.WinHttpHandler | `UNCHANGED` | 10.0.5 | 10.0.5 |
| System.Reflection.Context | `UNCHANGED` | 10.0.5 | 10.0.5 |
| System.Runtime.Caching | `UNCHANGED` | 10.0.5 | 10.0.5 |
| System.Security.Cryptography.Pkcs | `UNCHANGED` | 10.0.13 | 10.0.13 |
| System.Security.Cryptography.ProtectedData | `UNCHANGED` | 10.0.5 | 10.0.5 |
| System.Security.Cryptography.Xml | `UNCHANGED` | 10.0.13 | 10.0.13 |
| System.Security.Permissions | `UNCHANGED` | 10.0.5 | 10.0.5 |
| System.ServiceModel.Http | `UNCHANGED` | 10.0.652802 | 10.0.652802 |
| System.ServiceModel.NetFramingBase | `UNCHANGED` | 10.0.652802 | 10.0.652802 |
| System.ServiceModel.NetTcp | `UNCHANGED` | 10.0.652802 | 10.0.652802 |
| System.ServiceModel.Primitives | `UNCHANGED` | 10.0.652802 | 10.0.652802 |
| System.ServiceModel.Syndication | `UNCHANGED` | 10.0.5 | 10.0.5 |
| System.ServiceProcess.ServiceController | `UNCHANGED` | 10.0.5 | 10.0.5 |
| System.Speech | `UNCHANGED` | 10.0.5 | 10.0.5 |
| System.Web.Services.Description | `UNCHANGED` | 8.1.2 | 8.1.2 |
| System.Windows.Extensions | `UNCHANGED` | 10.0.5 | 10.0.5 |
| Tmds.DBus.Protocol | `UNCHANGED` | 0.94.1 | 0.94.1 |
| tqdm | `VERSION_OR_ARTIFACT_CHANGED_LICENSE_SAME` | 4.70.1 | 4.70.1 |
| wheel | `VERSION_OR_ARTIFACT_CHANGED_LICENSE_SAME` | 0.48.0 | 0.48.0 |

## Licence rules

The project's own code is read as **Apache-2.0** (the licence skeleton of the orchestrator).

| Component | Licence, as read | Chosen from | In the program as | Licence texts |
|---|---|---|---|---|
| img2pdf | `LGPL-3.0` | - | python_import | LGPL 3.0: in the component; GPL 3.0: standard text supplied |
| Inter | `OFL-1.1` | - | data | - |
| JetBrains Mono | `OFL-1.1` | - | data | - |
| Microsoft.Management.Infrastructure.Runtime.Win | `not recognised` | - | dynamic_library | - |
| packaging | `BSD-2-Clause` | Apache-2.0 or BSD-2-Clause | python_import | - |
| pikepdf | `MPL-2.0` | - | python_import | - |
| pymupdf | `GPL-3.0 AND Proprietary` | - | python_import | GPL 3.0: standard text supplied |
| tqdm | `MPL-2.0 AND MIT` | - | python_import | - |

Documents the collector added to the pack itself:

- GNU General Public License 3.0 (standard text) - LGPL-3.0 asks for a copy of the GPL 3.0: img2pdf, pymupdf

## Scope

Only the explicitly configured project and scan roots were inspected.
No neighboring projects or parent directories were searched.
