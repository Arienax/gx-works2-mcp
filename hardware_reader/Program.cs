using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.Runtime.InteropServices;
using System.Text.RegularExpressions;
using System.Web.Script.Serialization;

// This helper is deliberately separate from the Simulator2 gateway. It has no
// server, write-device, CPU-state, reset, force, or generic invocation command.
namespace PlcAi.HardwareReader
{
    internal static class Program
    {
        private static readonly JavaScriptSerializer Json = new JavaScriptSerializer { MaxJsonLength = 16384 };

        private static void Print(object value) { Console.WriteLine(Json.Serialize(value)); }

        private static int Integer(object value)
        {
            if (!(value is int)) throw new ArgumentException("invalid_integer");
            return (int)value;
        }

        private static Type ControlType()
        {
            string progId = IntPtr.Size == 8 ? "ActUtlType64.ActUtlType64" : "ActUtlType.ActUtlType";
            return Type.GetTypeFromProgID(progId, false);
        }

        [STAThread]
        private static int Main()
        {
            object control = null;
            bool opened = false;
            try
            {
                // Read at most one bounded request; stdin EOF ends the command.
                char[] buffer = new char[16385];
                int length = 0, count;
                while (length < buffer.Length && (count = Console.In.Read(buffer, length, buffer.Length - length)) > 0) length += count;
                if (length >= buffer.Length) throw new ArgumentException("request_too_large");
                Dictionary<string, object> request = Json.DeserializeObject(new string(buffer, 0, length)) as Dictionary<string, object>;
                if (request == null || !request.ContainsKey("operation")) throw new ArgumentException("invalid_request");
                if (Convert.ToString(request["operation"]) == "capabilities")
                {
                    if (request.Count != 1) throw new ArgumentException("invalid_request");
                    Print(new { status = "capabilities", backend = "mx_logical_station_read_only", mx_registered = ControlType() != null,
                                device_read = true, device_write = false, persistent_connection = false });
                    return 0;
                }
                if (request.Count != 4 || Convert.ToString(request["operation"]) != "read" || !request.ContainsKey("logical_station")
                    || !request.ContainsKey("addresses") || !request.ContainsKey("plc_model")) throw new ArgumentException("unsupported_operation");
                int station = Integer(request["logical_station"]);
                if (station < 0 || station > 1023) throw new ArgumentException("invalid_station");
                string model = Convert.ToString(request["plc_model"]);
                if (model != "FX3U" && model != "FX5U") throw new ArgumentException("unsupported_model");
                object[] raw = request["addresses"] as object[];
                if (raw == null || raw.Length < 1 || raw.Length > 64) throw new ArgumentException("invalid_addresses");
                List<string> addresses = new List<string>();
                foreach (object value in raw)
                {
                    string address = value as string;
                    if (address == null || !Regex.IsMatch(address, "^[XYMDSTC][0-9]{1,5}$")) throw new ArgumentException("invalid_address");
                    if (model == "FX3U" && (address[0] == 'X' || address[0] == 'Y') && !Regex.IsMatch(address.Substring(1), "^[0-7]+$"))
                        throw new ArgumentException("invalid_address");
                    if (addresses.Contains(address)) throw new ArgumentException("duplicate_address");
                    addresses.Add(address);
                }
                Type type = ControlType();
                if (type == null) { Print(new { status = "error", code = "mx_not_registered" }); return 2; }
                control = Activator.CreateInstance(type);
                dynamic mx = control;
                mx.ActLogicalStationNumber = station;
                int openCode = Convert.ToInt32(mx.Open(), CultureInfo.InvariantCulture);
                if (openCode != 0) { Print(new { status = "error", code = "mx_open_failed" }); return 2; }
                opened = true;
                Dictionary<string, int> values = new Dictionary<string, int>();
                foreach (string address in addresses)
                {
                    // T/C expose the current value, matching the existing IR
                    // device convention; they are not timer/counter done bits.
                    string device = address[0] == 'T' ? "TN" + address.Substring(1)
                        : address[0] == 'C' ? "CN" + address.Substring(1) : address;
                    int data = 0;
                    int readCode = Convert.ToInt32(mx.GetDevice(device, out data), CultureInfo.InvariantCulture);
                    if (readCode != 0) { Print(new { status = "error", code = "mx_read_failed" }); return 2; }
                    values.Add(address, data);
                }
                int closeCode = Convert.ToInt32(mx.Close(), CultureInfo.InvariantCulture);
                opened = false;
                if (closeCode != 0) { Print(new { status = "error", code = "mx_close_failed" }); return 2; }
                Print(new { status = "read", backend = "mx_logical_station_read_only", logical_station = station, values = values });
                return 0;
            }
            catch (ArgumentException) { Print(new { status = "error", code = "invalid_request" }); return 2; }
            catch (Exception) { Print(new { status = "error", code = "reader_failed" }); return 2; }
            finally
            {
                if (control != null)
                {
                    if (opened) { try { ((dynamic)control).Close(); } catch (Exception) { } }
                    if (Marshal.IsComObject(control)) Marshal.FinalReleaseComObject(control);
                }
            }
        }
    }
}
