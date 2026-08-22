**OnePulse — Solution Architecture (Simple View)**

*Step 3 of 10 \| Non-Technical Overview \| Ref: OnePulse PRD v1.0 \|
Author: Claude (Anthropic) \| Reviewer: Gopinath Dhayanandamurthy*

**What This Is**

OnePulse reads real project data from Azure DevOps and team status
updates, has AI investigate and write an executive status report, checks
its own work for quality, and requires a human leader to sign off before
anything is considered final. It serves multiple portfolios and programs
at once, each with its own secure, isolated data.

**How It Works**

|                                       |     |                                         |     |                            |     |                               |     |                      |
|---------------------------------------|-----|-----------------------------------------|-----|----------------------------|-----|-------------------------------|-----|----------------------|
| **Project Data (ADO + Team Updates)** | →   | **AI Investigates & Writes the Report** | →   | **AI Checks Its Own Work** | →   | **Leader Reviews & Approves** | →   | **Report Delivered** |

*Every prior week's report is remembered, so each new one shows real
progress or real setbacks — not a blank slate.*

**Who Uses It**

<table width="640" data-cellpadding="11" data-cellspacing="0">
<tbody>
<tr class="odd" data-valign="top">
<td width="190" data-bgcolor="#ddebf7"
style="background: #ddebf7; border: 1px solid #000000; padding: 0.11in 0.13in"><p><strong>Portfolio
Lead</strong></p>
<p>Sees every program's status at a glance, can request a fresh report
anytime, and can ask questions about any past or current report in plain
language.</p></td>
<td width="191" data-bgcolor="#fff2cc"
style="background: #fff2cc; border: 1px solid #000000; padding: 0.11in 0.13in"><p><strong>Program
Lead</strong></p>
<p>Previews the finished report for their program and gives the final
sign-off before it goes out — nothing publishes without this.</p></td>
<td width="190" data-bgcolor="#f2f2f2"
style="background: #f2f2f2; border: 1px solid #000000; padding: 0.11in 0.13in"><p><strong>Platform
Admin</strong></p>
<p>Sets up new portfolios and programs, and keeps an eye on overall cost
and system health.</p></td>
</tr>
</tbody>
</table>

  
  

**Why You Can Trust It**

✓ Every status is backed by real, cited evidence — never a generic
guess.

✓ The overall Red/Amber/Green rating is calculated by a fixed rule,
never left to AI judgment.

✓ Nothing is final until a human leader reviews and approves it.

✓ Every portfolio's data stays completely separate from every other
portfolio's.

✓ Cost and quality are watched continuously, with automatic alerts if
anything looks unusual.
