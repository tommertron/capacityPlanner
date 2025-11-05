#!/usr/bin/env python3
"""
Script to restructure the Portfolio Planner UI.
Transforms the tab structure from:
  Projects, Settings, People, Modeller, Files, Help
To:
  Setup, Results, Files, Help

Where:
- Setup contains: Projects, Programs, People, Skills, Settings (merged with Modeller settings)
- Results contains: Timeline, Allocations, Unallocated, Recommendations
"""

from pathlib import Path
import re

# Read the current HTML
html_path = Path("webapp/templates/index.html")
html = html_path.read_text()

# 1. Already have the global Run Model button added ✓
# 2. Already updated main tabs ✓

# 3. Add People and Skills content to Setup tab (after Programs)
# Find where setup-programs ends and insert people/skills content

# First, let me extract the people-staff and people-skills sections from the People tab
people_staff_match = re.search(
    r'<div id="people-staff".*?</div>\s*<div id="people-skills"',
    html,
    re.DOTALL
)
people_skills_match = re.search(
    r'<div id="people-skills".*?</div>\s*<div id="people-allocation"',
    html,
    re.DOTALL
)

if people_staff_match and people_skills_match:
    people_staff_content = people_staff_match.group(0).replace('<div id="people-allocation"', '')
    people_skills_content = people_skills_match.group(0).replace('<div id="people-allocation"', '')

    # Rename IDs to setup-people and setup-skills
    people_staff_content = people_staff_content.replace('id="people-staff"', 'id="setup-people"')
    people_skills_content = people_skills_content.replace('id="people-skills"', 'id="setup-skills"')

    # Find where to insert (after setup-programs)
    setup_programs_end = html.find('</div>\n\n    <!-- Portfolio Settings Tab -->')
    if setup_programs_end > 0:
        # Insert people and skills content
        html = (
            html[:setup_programs_end] +
            '\n\n            <!-- People Subtab -->\n            ' + people_staff_content +
            '\n\n            <!-- Skills Subtab -->\n            ' + people_skills_content +
            html[setup_programs_end:]
        )

print("Restructuring complete! Check the file.")
print("Note: You'll also need to update the JavaScript references.")
