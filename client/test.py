from AppKit import NSWorkspace
import time

time.sleep(2)
workspace = NSWorkspace.sharedWorkspace()
app = workspace.frontmostApplication()
print(app.localizedName())
print(app.bundleIdentifier())