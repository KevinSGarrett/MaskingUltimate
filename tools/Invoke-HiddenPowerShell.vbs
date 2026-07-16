Option Explicit

Dim command, exitCode, index, shell

If WScript.Arguments.Count < 1 Then
  WScript.Quit 64
End If

command = QuoteArgument(WScript.Arguments(0))
For index = 1 To WScript.Arguments.Count - 1
  command = command & " " & QuoteArgument(WScript.Arguments(index))
Next

Set shell = CreateObject("WScript.Shell")
exitCode = shell.Run(command, 0, True)
WScript.Quit exitCode

Function QuoteArgument(value)
  If InStr(CStr(value), Chr(34)) > 0 Then
    WScript.Quit 65
  End If
  QuoteArgument = Chr(34) & CStr(value) & Chr(34)
End Function
