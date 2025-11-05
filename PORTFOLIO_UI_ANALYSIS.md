# Portfolio Planner UI Structure & User Flow Analysis

## Executive Summary
Portfolio Planner is a capacity planning tool with a **6-tab main navigation** and **4 subtab structures** within tabs. The UI is designed to guide users through a workflow of portfolio setup → project/people configuration → model execution → results review.

---

## 1. MAIN TAB STRUCTURE

### Overview of All 6 Tabs

| Tab | Purpose | Input/Output | Status |
|-----|---------|--------------|--------|
| **Projects** | Define projects, programs, timelines | INPUT (Projects) + OUTPUT (Timeline) | Dynamic subtabs |
| **Portfolio Settings** | Configure planning constraints | INPUT | Settings config form |
| **People** | Manage staff, skills, allocations | INPUT (Staff/Skills) + OUTPUT (Allocations) | Dynamic subtabs |
| **Modeller** | Run capacity planning algorithm | EXECUTION | Job monitoring |
| **Files** | Access raw data files | Both | File browser |
| **Help** | Documentation & guidance | Reference | Static markdown |

### Key Insight: Tab Organization Pattern
- **2 INPUT-DOMINANT tabs**: Portfolio Settings, People (Staff/Skills)
- **2 OUTPUT-DOMINANT tabs**: Projects (Timeline), People (Allocations)
- **1 EXECUTION tab**: Modeller (runs the algorithm)
- **1 REFERENCE tab**: Help & Files

---

## 2. DETAILED TAB BREAKDOWN WITH SUBTABS

### TAB 1: PROJECTS (4 subtabs)
**Primary Input for Portfolio**

#### Subtab 1.1: Projects Input
- **Purpose**: Add/edit/delete individual projects
- **Content Type**: INPUT TABLE
- **Key Fields Per Project**:
  - Project ID (unique)
  - Project Name
  - Effort estimates (BA, Planner, Dev in person-months)
  - Priority (lower number = higher priority)
  - Parent Program
  - Required Skillsets
- **Actions Available**:
  - Add Project button (creates new row)
  - Inline editing (click cell to edit)
  - Delete button (trash icon per row)
  - Priority controls (up/down arrows)
  - Save/Discard Changes buttons
- **Visual Feedback**: 
  - Unsaved changes indicator (pulsing dot + text)
  - Changed cells highlighted in yellow
  - Program filter dropdown to view by program

#### Subtab 1.2: Programs
- **Purpose**: Manage program groupings for projects
- **Content Type**: INPUT TABLE
- **Key Fields Per Program**:
  - Program Name
  - Color (hex color picker)
- **Actions Available**:
  - Add Program button
  - Edit program details (modal popup)
  - Delete program
  - Color picker (visual and hex code)
  - Save/Discard Changes

#### Subtab 1.3: Timeline (OUTPUT)
- **Purpose**: View scheduling results AFTER model runs
- **Content Type**: OUTPUT VISUALIZATION
- **Display**: Gantt-chart style timeline
  - Rows: Projects with ID, name, program, duration
  - Columns: Months (auto-generated from data)
  - Cells: Colored bars showing project execution period
  - Color-coded by program assignment
- **Interactions**:
  - Sort by Program button
  - Sort by Start Date button
  - Program filter dropdown
- **Data Dependency**: Requires running the model first

#### Subtab 1.4: Unallocated (OUTPUT)
- **Purpose**: View projects that COULDN'T be scheduled
- **Content Type**: OUTPUT MARKDOWN
- **Display**: Explanatory text showing:
  - List of failed projects
  - Reasons why they couldn't schedule
  - Resource constraint analysis
- **Data Dependency**: Requires running the model first

---

### TAB 2: PORTFOLIO SETTINGS (no subtabs)
**Configuration Engine**

- **Purpose**: Define planning constraints and algorithm parameters
- **Content Type**: INPUT FORM
- **Key Configuration Sections**:
  1. **Planning Window**: Start date, End date (optional for open-ended)
  2. **KTLO Percentages**: "Keep The Lights On" by role (BA, Planner, Dev)
     - Default reserves for ongoing maintenance work
  3. **Max Concurrent Projects**: Per role limit
  4. **Planner Cap**: Max % allocation to single project per month
  5. **Effort Curves**: Distribution shape (uniform, bell curve, front-loaded, etc.)
  6. **Priority-Based Scheduling**: Enable/disable priority-first allocation
  7. **Overbooking Tolerance**: Allow slight overallocation %
- **Actions**: Save/Discard Changes buttons
- **Visual Feedback**: Unsaved changes indicator

**UX Note**: Changes persist immediately but need model re-run to affect timeline

---

### TAB 3: PEOPLE (4 subtabs)
**Resource & Staffing Management**

#### Subtab 3.1: Staff
- **Purpose**: Manage team members and their capabilities
- **Content Type**: INPUT CARDS (grid layout, not table)
- **Card Layout Per Person**:
  - Name
  - Roles (checkboxes: BA, Planner, Dev)
  - Active status (toggle)
  - Start/End dates (availability window)
  - Skillsets (tag input - add/remove skills)
  - Preferred Programs (tag input)
  - Notes
- **Actions Per Person**:
  - Edit button (opens modal)
  - Delete button (trash icon)
- **Top-level Action**: "Add Person" button
- **Organization**: Grouped by role (BA, Planner, Dev sections)

#### Subtab 3.2: Skills
- **Purpose**: Define available skills in the portfolio
- **Content Type**: INPUT TABLE/FORM
- **Key Fields Per Skill**:
  - Skill ID (lowercase-with-dashes format)
  - Skill Name
  - Category (BA, Dev, Planner, General)
  - Description
- **Actions**:
  - Add Skill button (opens modal)
  - Edit skill (modal)
  - Delete skill
  - Save/Discard changes

#### Subtab 3.3: Resource Allocation (OUTPUT)
- **Purpose**: View results AFTER model runs - heatmap of utilization
- **Content Type**: OUTPUT HEATMAP TABLE
- **Structure**:
  - Rows: Roles (collapsible) → People (nested, expandable) → Projects (detail rows)
  - Columns: Months (auto-generated)
  - Cells: Allocation percentage with color coding
- **Color Coding**:
  - Light blue (0-30%): Low utilization
  - Medium blue (40-70%): Healthy utilization
  - Dark blue (80-100%): Full utilization
  - Red (>100%): OVERALLOCATED (alert color)
  - Gray (#f0f0f0): 0%
- **Interactions**:
  - Click role names to expand/collapse people
  - Click person names to expand/collapse project details
  - Editable cells (can manually adjust allocations)
  - Save edits button, Discard changes button
  - Visual change tracking (modified cells marked with *)
- **Nested Hierarchy**:
  ```
  Role (BA, Planner, Dev)
    ├── Total for role (aggregate)
    ├── Person A
    │   ├── Total for person
    │   ├── Project X  (detail row with KTLO)
    │   └── Project Y
    └── Person B
  ```

#### Subtab 3.4: Resourcing Recommendations (OUTPUT)
- **Purpose**: AI-generated staffing suggestions
- **Content Type**: OUTPUT MARKDOWN + CHARTS
- **Display**: 
  - Text analysis of hiring needs
  - Charts showing capacity gaps
  - Recommendations for team changes
- **Data Dependency**: Requires aggressive allocation mode + model run
- **Typical Content**:
  - Skill gaps identified
  - Team size recommendations
  - Hiring priority suggestions

---

### TAB 4: MODELLER (no subtabs)
**Execution & Job Monitoring**

#### Modeller Settings Section (Dynamic)
- **Purpose**: Configure and launch the scheduling algorithm
- **Content Type**: INPUT FORM + LAUNCH BUTTON
- **Configuration Options**:
  - Portfolio selector (dropdown)
  - Allocation mode selector (normal vs aggressive)
  - Constraint review (read-only summary)
  - "Run Model" button
- **Instructions Box**: Embedded help text
  - Validate data is ready
  - Confirm configuration
  - Explain what happens next

#### Recent Jobs Table (OUTPUT)
- **Purpose**: Monitor algorithm execution progress
- **Content Type**: OUTPUT TABLE
- **Columns**:
  - Job ID (link to status page)
  - Portfolio
  - State (queued, running, done, failed)
  - Created At
  - Started At
  - Finished At
  - Message
- **Status Classes** (CSS styling):
  - queued → gray text
  - running → blue text
  - done → green text
  - failed → red text
- **Auto-polling**: Frontend polls job status every N seconds while running
- **Behavior**:
  - New jobs appear at top of table
  - Job status updates in real-time
  - Color changes reflect state
  - Model results auto-populate in other tabs when done

---

### TAB 5: FILES (no subtabs)
**Direct File Access**

- **Purpose**: Browse input/output files
- **Content Type**: FILE BROWSER
- **Displays**:
  - Input Files (read-only download):
    - projects.csv
    - people.json
    - config.json
    - programs.csv
  - Output Files (result downloads):
    - project_timeline.csv
    - resource_capacity.csv
    - unallocated_projects.md
  - Timestamp info
- **Actions**: Download/view links per file

---

### TAB 6: HELP (no subtabs)
**Documentation**

- **Purpose**: User guidance and troubleshooting
- **Content Type**: STATIC MARKDOWN
- **Sections**:
  1. Overview
  2. Getting Started (portfolio creation)
  3. Tab-by-tab walkthroughs
  4. Best Practices
  5. Tips & Tricks
  6. Troubleshooting
  7. Data Format Notes
- **No Interactivity**: Pure reference content

---

## 3. TYPICAL USER WORKFLOW (Start to Finish)

### Phase 1: Portfolio Setup (First-Time User)
```
1. Click "+ New Portfolio" button
2. Enter portfolio name (alphanumeric + dash/underscore)
3. System creates folder with sample data
4. Portfolio selector auto-updates
5. Portfolio selected and ready to customize
```

### Phase 2: Data Configuration (Input)
```
Sequential or parallel (user can jump around):

A. PROJECTS TAB → Projects Subtab
   - Review sample projects OR add new ones
   - Define effort (BA/Planner/Dev person-months)
   - Assign to programs
   - Set priorities (lower = higher priority)
   - Add required skillsets

B. PROJECTS TAB → Programs Subtab
   - Create program groups (optional but recommended)
   - Assign colors to programs
   - Organize projects visually

C. PORTFOLIO SETTINGS TAB
   - Define planning window (start/end dates)
   - Set KTLO percentages (typical: 10-20%)
   - Configure Max Concurrent Projects
   - Adjust Planner Cap if needed
   - Choose effort curve style
   - Enable priority-based scheduling

D. PEOPLE TAB → Staff Subtab
   - Add team members
   - Assign roles (can be multiple per person)
   - Set availability (start/end dates)
   - Add skillsets matching project requirements
   - Indicate program preferences (optional)

E. PEOPLE TAB → Skills Subtab
   - Define available skills in portfolio
   - Use consistent naming (lowercase-dashed)
   - Categorize by role
```

### Phase 3: Algorithm Execution (Processing)
```
1. MODELLER TAB
   - Select portfolio from dropdown
   - Choose allocation mode (Normal or Aggressive)
   - Review constraints summary
   - Click "Run Model"

2. Monitor Job Status
   - Watch "Recent Jobs" table
   - Job state: queued → running → done/failed
   - See timestamps and status messages

3. Wait for Completion
   - Poll shows real-time updates
   - Typically 30 seconds to several minutes
   - System auto-updates other tabs when done
```

### Phase 4: Results Review (Output Analysis)
```
A. PROJECTS TAB → Timeline Subtab
   - See Gantt chart of scheduled projects
   - View start/end months for each project
   - Program color-coding shows project groupings
   - Can sort by Program or Start Date
   - Can filter by specific program

B. PROJECTS TAB → Unallocated Subtab
   - Review projects that couldn't fit in schedule
   - Read explanations (resource constraints, etc.)
   - Identify capacity bottlenecks
   - Understand what prevented scheduling

C. PEOPLE TAB → Resource Allocation Subtab
   - View heatmap of team utilization
   - Expand roles to see individual people
   - Expand people to see project-level allocations
   - Identify overallocated team members (red cells)
   - Manually adjust allocations if needed (edit mode)

D. PEOPLE TAB → Resourcing Recommendations Subtab (if Aggressive mode used)
   - Read AI-generated hiring suggestions
   - See skill gaps identified
   - Get team size recommendations
```

### Phase 5: Iteration & Refinement (Repeat)
```
If results aren't satisfactory:
- Go back to relevant INPUT tabs
- Modify projects (scope, effort, priority)
- Adjust people (add/remove team, change allocations)
- Change settings (KTLO, constraints)
- Re-run model (Modeller tab)
- Review new results
- Repeat until satisfied
```

---

## 4. INFORMATION ARCHITECTURE FLOW DIAGRAM

```
┌─────────────────────────────────────────────────────────────────┐
│  PORTFOLIO PLANNER                                              │
│  [Portfolio Selector Dropdown] [+ New Portfolio Button]         │
└─────────────────────────────────────────────────────────────────┘

┌─ INPUT DATA ─────────────┐  ┌─ CONFIGURATION ──┐  ┌─ EXECUTION ───┐
│                           │  │                  │  │               │
│ PROJECTS                  │  │ PORTFOLIO        │  │ MODELLER      │
│ ├─ Projects (subtab)      │  │ SETTINGS (tab)   │  │ ├─ Settings   │
│ │  INPUT: Add/Edit/Delete │  │ INPUT: Params    │  │ │ ├─ Portfolio│
│ │  projects with effort   │  │ & constraints    │  │ │ ├─ Mode     │
│ │                         │  │                  │  │ │ └─ Run Btn  │
│ ├─ Programs (subtab)      │  │                  │  │ │             │
│ │  INPUT: Organize,       │  │                  │  │ └─ Jobs Table│
│ │  color-code projects    │  │                  │  │    OUTPUT:    │
│ │                         │  │                  │  │    Status &   │
│ ├─ Timeline (subtab)      │  │                  │  │    Progress   │
│ │  OUTPUT: Gantt chart    │  │                  │  │               │
│ │  after model runs       │  │                  │  │               │
│ │                         │  │                  │  │               │
│ └─ Unallocated (subtab)   │  │                  │  └───────────────┘
│    OUTPUT: Failed         │  │                  │
│    projects with reasons  │  │                  │
│                           │  └──────────────────┘
├─────────────────────────────────────────────────────────────┤
│                                                               │
│ PEOPLE                                                        │
│ ├─ Staff (subtab)                                            │
│ │  INPUT: Add/Edit people, roles, skills                    │
│ │                                                             │
│ ├─ Skills (subtab)                                           │
│ │  INPUT: Define skill library                              │
│ │                                                             │
│ ├─ Resource Allocation (subtab)                              │
│ │  OUTPUT: Heatmap of utilization by person/month           │
│ │  EDITABLE: Can manually adjust allocations                │
│ │                                                             │
│ └─ Resourcing Recommendations (subtab)                       │
│    OUTPUT: AI suggestions (aggressive mode only)            │
│                                                               │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│ FILES (tab) - Download raw input/output files                │
│                                                               │
│ HELP (tab) - Documentation & guidance                        │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

---

## 5. POTENTIAL UX PAIN POINTS & CONFUSION AREAS

### Critical Pain Points (Likely to Confuse New Users)

1. **Portfolio Selection is Prerequisite but Not Obvious**
   - Problem: UI doesn't clearly communicate "select portfolio first"
   - Symptom: User clicks tabs, sees "Select a portfolio..." message everywhere
   - Solution: Add visual cue or wizard on first load
   - Severity: HIGH

2. **Input vs Output Tabs Blended**
   - Problem: Projects tab mixes input (Projects/Programs) with output (Timeline/Unallocated)
   - Symptom: Users might expect to see Timeline immediately; doesn't exist until model runs
   - Solution: Separate or clearly label which requires model execution
   - Severity: MEDIUM

3. **Hidden Dependency: Model Must Run for Results**
   - Problem: Timeline and Allocations tabs are empty by default
   - Symptom: User configures everything, then wonders "where are my results?"
   - Solution: Explicit messaging like "Run Modeller → go to Projects → Timeline to view results"
   - Severity: HIGH

4. **Implicit Data Flow Not Visible**
   - Problem: User doesn't understand which changes require model re-run vs immediate effect
   - Symptom: User edits project priority, expects timeline to update without re-running
   - Symptom: User expects changing KTLO % to auto-update allocations
   - Solution: Add persistent banner "Model outdated - run to refresh results"
   - Severity: MEDIUM

5. **Editable Allocation Cells Look Like View-Only**
   - Problem: Resource Allocation table looks like output only
   - Symptom: Users don't realize they can edit individual allocation cells
   - Solution: Visual hint (cursor change, tooltip) to indicate editability
   - Severity: MEDIUM

6. **Skills Connection Not Obvious**
   - Problem: Users define skills in People → Skills, but unclear how they match to projects
   - Symptom: User doesn't know projects require skill specifications
   - Symptom: Scheduler fails because skillset requirements not satisfied
   - Solution: Help text linking Skills tab to Projects tab requirements
   - Severity: MEDIUM

7. **Program Filter State Persists Unexpectedly**
   - Problem: Selecting a program filter in one subtab might not be visible in another
   - Symptom: User filters by "Program A" in Projects input, doesn't see it in Timeline
   - Solution: Sync filter state across subtabs or show current filter prominently
   - Severity: LOW

8. **Unsaved Changes Indicator Inconsistency**
   - Problem: Some tabs show "Unsaved changes" indicator, others don't
   - Symptom: User thinks they saved when they didn't, loses work
   - Solution: Consistent unsaved state indicator across all editable tabs
   - Severity: MEDIUM

9. **No Onboarding for First-Time Users**
   - Problem: New user doesn't know order of operations
   - Symptom: User creates portfolio, doesn't know where to start
   - Solution: Guided tour or "Quick Start" wizard
   - Severity: HIGH

10. **Aggressive Mode Not Clearly Explained**
    - Problem: Users don't understand difference between Normal and Aggressive allocation modes
    - Symptom: User selects Aggressive but doesn't get recommendations
    - Solution: Tooltip or modal explaining mode differences
    - Severity: LOW-MEDIUM

### Secondary Pain Points (Minor Friction)

- **Too Many Tabs**: 6 main tabs might overwhelm
- **Subtab Organization**: Why are 2 input types under Projects but only 1 under Settings?
- **Modal Dialogs**: Person/Program/Skill editing in modals - not ideal for large datasets
- **No Bulk Operations**: Can't add 10 people at once via bulk import
- **Datetime Inputs**: Date format validation could be clearer
- **No Undo**: Discard Changes only works before saving; no undo after
- **Status Messages**: Brief status text in jobs table; no detailed error logging

---

## 6. UX PATTERNS IDENTIFIED

### Design Patterns Used

1. **Tab-based Navigation**
   - Main tabs for major feature areas
   - Subtabs for related views (input vs output)
   - Standard desktop application pattern

2. **Inline Editing**
   - Click cell to edit directly (Projects table)
   - Yellow highlighting for changed cells
   - Save/Discard buttons control persistence

3. **Modal Dialogs**
   - Used for adding/editing discrete items (people, programs, skills)
   - Good for forms that need confirmation
   - Overlay pattern

4. **Unsaved State Indicators**
   - Pulsing dot + text message
   - Shows which changes haven't persisted
   - Buttons appear/disappear based on state

5. **Color Coding**
   - Programs have assigned colors in Gantt chart
   - Allocation heatmap uses blue shades for utilization
   - Red for alerts (overallocation)
   - Gray for empty (0% allocation)

6. **Hierarchy Expansion**
   - Resource Allocation table: click row to expand/collapse children
   - Roles → People → Projects hierarchy
   - Disclosure triangle visual cue

7. **Filter + Sort Pattern**
   - Program filter dropdown in multiple tabs
   - Sort buttons for Timeline view
   - Stateful (persists during session)

8. **Polling for Async Tasks**
   - Modeller runs jobs asynchronously
   - Frontend polls job status every few seconds
   - Real-time table updates without page refresh

9. **Empty States**
   - "Select a portfolio to..." message before data available
   - Clear, actionable language
   - Guides user to next step

10. **Form Validation**
    - Inline validation (skill ID must be lowercase-dashed)
    - Pattern validation in HTML5
    - Error highlighting (red border)

---

## 7. RECOMMENDED FIRST-TIME USER JOURNEY

### Optimal Onboarding Flow

```
Step 1: Portfolio Creation
  UI: Highlight "+ New Portfolio" button
  Action: Click → Enter name → System creates with sample data
  Result: Portfolio selected and ready

Step 2: Review Sample Data (Optional but Recommended)
  UI: Auto-navigate to Projects → Projects subtab
  Action: User sees sample projects
  Message: "This portfolio includes sample data. Customize or replace with your own."

Step 3: Quick Configuration Checklist
  UI: Portfolio Settings tab with highlighted sections
  Checklist:
    ☐ Set Planning Start Date
    ☐ Set Planning End Date (or leave blank for open-ended)
    ☐ Adjust KTLO % by role (defaults: BA 15%, Planner 15%, Dev 20%)
    ☐ Review Max Concurrent Projects (default: 2)
  Message: "These settings control how the algorithm schedules work"

Step 4: People Setup
  UI: People → Staff subtab
  Action: Add team members or customize sample people
  Required: Name, at least one role (BA/Planner/Dev)
  Optional: Skillsets, availability dates, program preferences

Step 5: Project Setup (if customizing)
  UI: Projects → Projects subtab
  Action: Add/edit projects or keep samples
  Required: Project ID, Name, Effort (in person-months), Priority
  Optional: Program assignment, required skillsets

Step 6: Skills Definition
  UI: People → Skills subtab
  Action: Define skills to match project requirements
  Message: "Projects can require specific skills (e.g., 'back-end', 'security')"

Step 7: Run the Model
  UI: Modeller tab - highlighted with attention-grabbing styling
  Action: Click "Run Model"
  Feedback: Job appears in table, status updates in real-time
  Message: "Model is running... this typically takes 30-60 seconds"

Step 8: Review Timeline Results
  UI: Projects → Timeline subtab
  Action: See Gantt chart of scheduled projects
  Message: "Your projects are scheduled in priority order. Projects in red failed to schedule due to resource constraints."

Step 9: Analyze Allocations
  UI: People → Resource Allocation subtab
  Action: Explore heatmap, expand roles and people
  Message: "Blue indicates healthy allocation. Red indicates overallocation. You can manually adjust cells here."

Step 10: Check for Unallocated Projects
  UI: Projects → Unallocated subtab
  Action: Review why projects failed to schedule
  Decision: Iterate by adjusting priorities, effort, team size, or constraints

Step 11: Iterate (Loop back to step 3 or 4)
  UI: Visual cue showing "Model is outdated" if changes made
  Action: Make adjustments and re-run model
```

---

## 8. KEY DATA FLOW INSIGHTS

### Data Dependencies

```
INPUT SOURCES:
├─ Projects (user enters in Projects tab)
├─ Programs (optional grouping)
├─ Portfolio Settings / Config (user sets constraints)
├─ People / Staff (user enters)
└─ Skills (user defines)

         ↓ (all required)
    
    MODELLER (algorithm)
    - Takes all inputs
    - Applies constraints
    - Generates schedule
    
         ↓ (produces)

OUTPUT DESTINATIONS:
├─ Project Timeline (when/how long each project runs)
├─ Resource Allocation (heatmap of person/project/month)
├─ Unallocated Projects (what couldn't schedule + why)
└─ Resourcing Recommendations (skill gaps, hiring needs)
```

### State Management

**Stateful Elements** (persist across navigation):
- Selected portfolio (localStorage)
- Program filter selections (session)
- Timeline sort mode (session)
- Unsaved changes tracking (in-memory)

**Cached Data**:
- Timeline data (reused if portfolio hasn't changed)
- Unallocated markdown (reused if portfolio hasn't changed)
- Program color map (regenerated on portfolio change)

---

## 9. SUMMARY TABLE: TAB FEATURES AT A GLANCE

| Feature | Input/Output | User Action | Subtabs? | Saves? | Requires Model? |
|---------|-----------|-------------|----------|--------|---|
| Add Projects | INPUT | Click add, fill form | Yes (4) | Yes | No |
| Add Programs | INPUT | Click add, fill form | Yes (4) | Yes | No |
| View Timeline | OUTPUT | Auto-generated | Yes (4) | N/A | **YES** |
| View Unallocated | OUTPUT | Auto-generated | Yes (4) | N/A | **YES** |
| Portfolio Settings | INPUT | Fill form | No | Yes | No* |
| Add People | INPUT | Click add, fill modal | Yes (4) | Yes | No |
| Add Skills | INPUT | Click add, fill modal | Yes (4) | Yes | No |
| View Allocations | OUTPUT | Auto-generated | Yes (4) | N/A | **YES** |
| Edit Allocations | INPUT (hybrid) | Click cell, edit | Yes (4) | Yes | No |
| Run Model | EXECUTION | Click button, monitor | No | N/A | N/A |
| View Job Status | OUTPUT | Monitor table | No | N/A | N/A |
| Download Files | OUTPUT | Click link | No | N/A | N/A |

*Portfolio Settings changes require re-running model to see effect

---

## CONCLUSION

The Portfolio Planner UI successfully implements a **input → processing → output** workflow appropriate for capacity planning. However, the lack of explicit workflow guidance and the mixing of input/output in the same tabs create friction for new users. 

**Key recommendations:**
1. Add onboarding wizard or guided tour
2. Clearly separate input and output sections
3. Add persistent "Model Status" indicator
4. Improve visibility of which tabs are editable vs read-only
5. Add inline help and tooltips for complex concepts
6. Consider "Getting Started" mode vs "Advanced" mode views
