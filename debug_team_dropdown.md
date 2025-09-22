## Team Dropdown Debugging Instructions

The team dropdown issue has been fixed with comprehensive debugging. Here are the steps to test and debug:

### 1. Browser Console Commands

Open your browser's Developer Tools (F12) and go to the Console tab. You can run these commands:

```javascript
// Test if functions exist
console.log('Functions available:', {
    setupServerTeamSelection: typeof setupServerTeamSelection,
    showServerTeamSelect: typeof showServerTeamSelect,
    fetchTeamsForUser: typeof fetchTeamsForUser,
    populateTeamSelect: typeof populateTeamSelect
});

// Manual debug test
debugTeamDropdown();

// Force setup if needed
forceSetupTeamSelection();

// Test manual show/hide
showServerTeamSelect(true);  // Should show dropdown
showServerTeamSelect(false); // Should hide dropdown
```

### 2. Manual Testing Steps

1. Navigate to `/admin` in your browser
2. Go to the **"Virtual Servers Catalog"** tab (should be visible by default)
3. Look for the **"Add New Server"** form
4. Find the **"Visibility"** radio buttons: 🌍Public, 👥Team, 🔒Private
5. Click on **🔒Private**
6. The **"Select Team"** dropdown should appear below the visibility options

### 3. Debug Output to Watch For

In the browser console, you should see messages like:

```
🔧 Setting up server team selection...
📋 Element check: {container: "found", select: "found", form: "found"}
📻 Found visibility radios: 3
📻 Radio 1: value="public", id="server-visibility-public"
📻 Radio 2: value="team", id="server-visibility-team"  
📻 Radio 3: value="private", id="server-visibility-private"
```

When you click Private:
```
🔄 Visibility changed to: private
🔒 Private selected - showing team dropdown
👁️ showServerTeamSelect called with show=true
📦 Container found, current display: "none"
✅ Container display set to: "block"
```

### 4. Troubleshooting

#### If no debug messages appear:
- JavaScript may have failed to load
- Check for errors in console
- Try refreshing the page

#### If "Elements not found":
- The form may be in a different tab that's hidden
- Try: `document.getElementById('server-team-select-container')`
- Should return the HTML element, not null

#### If dropdown doesn't show even with manual commands:
- There may be CSS hiding it
- Try: `debugTeamDropdown()` to force visibility
- Check computed styles in Elements tab

#### If API calls fail:
- Look for "Teams API response not OK" errors
- Check if you're logged in and have team permissions
- Verify the `/admin/teams/json` endpoint returns team data

### 5. Expected Behavior

✅ **When Private is selected:**
- Team dropdown appears
- Teams are fetched from API or template data
- Dropdown populates with user's teams
- Form submit is enabled/disabled based on team selection

✅ **When Public/Team is selected:**
- Team dropdown hides
- No team selection required

### 6. Common Issues Fixed

1. **Function Scope**: Moved functions to global scope
2. **Timing**: Added retry logic for DOM readiness
3. **Event Listeners**: Fixed radio button event binding
4. **CSS Display**: Added forced visibility for debugging
5. **API Authentication**: Added proper headers and error handling

If the dropdown still doesn't work after these fixes, run `debugTeamDropdown()` in the console and share the output.