import re
import streamlit as st
from datetime import datetime, timedelta


def apply_ev_cashout_patch(lines):
    patched_lines = []
    current_hand = []

    for line in lines:
        if line.startswith("CoinPoker Hand #"):
            if current_hand:
                patched_lines.extend(fix_single_hand(current_hand))
            current_hand = [line]
        else:
            if current_hand:
                current_hand.append(line)
            else:
                patched_lines.append(line)
    if current_hand:
        patched_lines.extend(fix_single_hand(current_hand))

    return patched_lines


def fix_single_hand(hand_lines):
    net_pot = 0.0
    collected_data = {}
    shows_lines = []
    shows_seen = set()
    true_gross_pot = None
    total_rake = 0.0

    for line in hand_lines:
        if line.startswith("# TRUE_GROSS_POT"):
            true_gross_pot = float(line.split()[2])

        if line.startswith("Total pot "):
            m = re.match(r"^Total pot \$([\d\.]+) \| Rake \$([\d\.]+)", line)
            if m:
                total_rake = float(m.group(2))
                if true_gross_pot is None:
                    net_pot = round(float(m.group(1)) - total_rake, 2)

        coll_m = re.match(r"^(.*?)(?: collected )\$([\d\.]+)( from pot.*)$", line)
        if coll_m:
            player = coll_m.group(1)
            collected_data[player] = collected_data.get(player, 0.0) + float(coll_m.group(2))

        if ": shows [" in line:
            player = line.split(":")[0]
            if player not in shows_seen:
                shows_lines.append(line)
                shows_seen.add(player)

    if true_gross_pot is not None:
        net_pot = round(true_gross_pot - total_rake, 2)

    if not collected_data:
        return [l for l in hand_lines if not l.startswith("# TRUE_GROSS_POT")]

    sum_collected = round(sum(collected_data.values()), 2)
    diff = round(net_pot - sum_collected, 2)

    if abs(diff) >= 0.01:
        if abs(diff) <= 0.10:
            max_p = max(collected_data, key=collected_data.get)
            collected_data[max_p] = round(collected_data[max_p] + diff, 2)
            final_collected = collected_data
        else:
            max_amt = max(collected_data.values())
            true_winners = [p for p, amt in collected_data.items() if amt >= max_amt - 0.05]

            win_share = round(net_pot / len(true_winners), 2)
            final_collected = {p: win_share for p in true_winners}

            rem_diff = round(net_pot - sum(final_collected.values()), 2)
            if rem_diff != 0.0:
                final_collected[true_winners[0]] = round(final_collected[true_winners[0]] + rem_diff, 2)
    else:
        final_collected = collected_data

    fixed_hand = []
    in_showdown = False
    in_summary = False

    for line in hand_lines:
        if line.startswith("# TRUE_GROSS_POT"):
            continue

        if line == "*** SHOW DOWN ***":
            in_showdown = True
            fixed_hand.append(line)
            for sl in shows_lines:
                fixed_hand.append(sl)
            for p, amt in final_collected.items():
                fixed_hand.append(f"{p} collected ${amt:.2f} from pot")
            continue

        if line.startswith("*** SUMMARY ***"):
            in_showdown = False
            in_summary = True
            fixed_hand.append(line)
            continue

        if in_showdown:
            continue

        if in_summary:
            if " won " in line or " lost " in line:
                summary_m = re.match(r"^(Seat \d+: (.*?))(?: showed (\[.*?\]))?(?: and)? (?:won|lost)", line)
                if summary_m:
                    prefix = summary_m.group(1)
                    player = summary_m.group(2)
                    cards = summary_m.group(3)

                    with_m = re.search(r"with ([a-zA-Z0-9 ]+)", line)
                    with_str = f" with {with_m.group(1).strip()}" if with_m else ""

                    if player in final_collected:
                        if cards:
                            fixed_line = f"{prefix} showed {cards} and won (${final_collected[player]:.2f}){with_str}"
                        else:
                            fixed_line = f"{prefix} won (${final_collected[player]:.2f}){with_str}"
                    else:
                        if cards:
                            fixed_line = f"{prefix} showed {cards} and lost{with_str}"
                        else:
                            fixed_line = f"{prefix} lost{with_str}"

                    fixed_hand.append(fixed_line)
                    continue

        coll_m = re.match(r"^(.*?)(?: collected )\$([\d\.]+)( from pot.*)$", line)
        if coll_m and not in_showdown:
            player = coll_m.group(1)
            if player in final_collected:
                fixed_hand.append(f"{player} collected ${final_collected[player]:.2f} from pot")
            continue

        fixed_hand.append(line)

    return fixed_hand


def convert_coinpoker_to_pt4_memory(lines, hero_name="Hero"):
    converted_lines = []

    current_street_invested = {}
    current_max_bet = 0.0
    splash_amount = 0.0
    true_gross_pot = 0.0

    for line in lines:
        line = line.strip()

        if not line:
            converted_lines.append("")
            continue

        if "SPLASH dropped" in line:
            splash_match = re.search(r"SPLASH dropped [\$₮]([\d\.]+)", line)
            if splash_match:
                splash_amount += float(splash_match.group(1))
            continue

        if (line.startswith("*** SECOND ") or line.startswith("*** THIRD ") or line.startswith(
                "*** FOURTH ")) and "SHOWDOWN" not in line:
            continue
        if line.startswith("SECOND Board") or line.startswith("THIRD Board") or line.startswith("FOURTH Board"):
            continue
        if line in ["*** SECOND SHOWDOWN ***", "*** THIRD SHOWDOWN ***", "*** FOURTH SHOWDOWN ***"]:
            continue
        if line.startswith("Hand was run "):
            continue

        if line.startswith("*** FIRST "):
            line = line.replace("*** FIRST ", "*** ")
        if line.startswith("FIRST Board"):
            line = line.replace("FIRST Board", "Board")

        header_match = re.match(
            r"CoinPoker Hand #(\d+): NLH \([\$₮]([\d\.]+)/[\$₮]([\d\.]+)(?:/[\$₮]([\d\.]+))?\) (\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}) CEST",
            line.replace("₮", "$"))
        if header_match:
            splash_amount = 0.0
            current_street_invested = {}
            current_max_bet = 0.0
            true_gross_pot = 0.0

            hand_id = header_match.group(1)
            sb = header_match.group(2)
            bb = header_match.group(3)
            time_str = header_match.group(5)

            dt_cest = datetime.strptime(time_str, "%Y/%m/%d %H:%M:%S")
            dt_utc = dt_cest - timedelta(hours=2)
            utc_str = dt_utc.strftime("%Y/%m/%d %H:%M:%S")

            new_header = f"CoinPoker Hand #{hand_id}: Hold'em No Limit (${sb}/${bb} USD) - {utc_str} UTC"
            converted_lines.append(new_header)
            continue

        line = line.replace("₮", "$").replace("Hero", hero_name)

        if line.startswith("Dealt to ") and hero_name not in line:
            continue

        uncalled_match = re.match(r"^(.*?): RETURN \$([\d\.]+)$", line)
        if uncalled_match:
            player = uncalled_match.group(1)
            amount_str = uncalled_match.group(2)
            amount = float(amount_str)
            if player in current_street_invested:
                current_street_invested[player] = round(current_street_invested[player] - amount, 2)
            converted_lines.append(f"Uncalled bet (${amount_str}) returned to {player}")
            continue

        ante_match = re.match(r"^(.*?): posts ante \$([\d\.]+)$", line)
        if ante_match:
            p = ante_match.group(1)
            amt = float(ante_match.group(2))
            true_gross_pot = round(true_gross_pot + amt, 2)
            converted_lines.append(f"{p}: posts the ante ${amt:.2f}")
            continue

        is_street_marker = (
                line.startswith("*** FLOP ***") or
                line.startswith("*** TURN ***") or
                line.startswith("*** RIVER ***") or
                line.startswith("*** SHOW DOWN ***") or
                line.startswith("*** SHOWDOWN ***") or
                line.startswith("*** FIRST SHOWDOWN ***") or
                line.startswith("*** SUMMARY ***")
        )
        if is_street_marker:
            true_gross_pot = round(true_gross_pot + sum(current_street_invested.values()), 2)
            current_street_invested = {}
            current_max_bet = 0.0

        posts_match = re.match(r"^(.*?): posts \$([\d\.]+)$", line)
        if posts_match:
            line = f"{posts_match.group(1)}: posts big blind ${posts_match.group(2)}"

        if ": STRADDLE $" in line:
            line = re.sub(r": STRADDLE \$([\d\.]+)", r": posts straddle $\1", line)

        line_processed = False

        if not line_processed:
            raise_match = re.match(r"^(.*?): raises \$([\d\.]+) to \$([\d\.]+)", line)
            if raise_match:
                p = raise_match.group(1)
                total_bet = float(raise_match.group(3))
                current_street_invested[p] = round(total_bet, 2)
                if total_bet > current_max_bet:
                    current_max_bet = total_bet
                line_processed = True

        if not line_processed:
            allin_match = re.match(r"^(.*?): ALLIN \$([\d\.]+)", line)
            if allin_match:
                p = allin_match.group(1)
                added_amt = float(allin_match.group(2))
                current_in = current_street_invested.get(p, 0.0)
                new_total = round(current_in + added_amt, 2)

                if current_max_bet == 0.0:
                    line = f"{p}: bets ${added_amt:.2f} and is all-in"
                    current_max_bet = new_total
                elif new_total > current_max_bet:
                    raise_amt = round(new_total - current_max_bet, 2)
                    line = f"{p}: raises ${raise_amt:.2f} to ${new_total:.2f} and is all-in"
                    current_max_bet = new_total
                else:
                    line = f"{p}: calls ${added_amt:.2f} and is all-in"

                current_street_invested[p] = new_total
                line_processed = True

        if not line_processed:
            action_match = re.match(r"^(.*?): (posts .*?|calls|bets) \$([\d\.]+)", line)
            if action_match:
                p = action_match.group(1)
                amt = float(action_match.group(3))
                current_street_invested[p] = round(current_street_invested.get(p, 0.0) + amt, 2)
                if current_street_invested[p] > current_max_bet:
                    current_max_bet = current_street_invested[p]

        if "didn't show" in line:
            line = line.replace("didn't show", "mucked")

        if line == "*** SHOWDOWN ***" or line == "*** FIRST SHOWDOWN ***":
            line = "*** SHOW DOWN ***"

        if line.startswith("Total pot "):
            pot_match = re.match(r"^Total pot \$([\d\.]+) \| Rake \$([\d\.]+)(?: \| Splash Fee \$([\d\.]+))?", line)
            if pot_match:
                rake = float(pot_match.group(2))
                splash_fee = float(pot_match.group(3)) if pot_match.group(3) else 0.0
                total_rake = round(rake + splash_fee, 2)

                new_pot = true_gross_pot

                converted_lines.append(f"# TRUE_GROSS_POT {new_pot:.2f}")
                line = f"Total pot ${new_pot:.2f} | Rake ${total_rake:.2f}"

        if line == "Hand was run once" or line.startswith("Game ended:"):
            continue

        converted_lines.append(line)

    return apply_ev_cashout_patch(converted_lines)


# --- INTERFEJS STREAMLIT (UI) ---
st.set_page_config(page_title="CoinPoker to PT4 Converter", page_icon="♠️", layout="centered")

st.title("♠️ CoinPoker -> PT4 Converter")
st.markdown("A seamless hand converter with full support for Ante, Run It Twice, and Splash Pot auditing.")

st.warning(
    "**⚠️ Important Notes:**\n"
    "- Doesn't process bomb pots\n"
    "- Doesn't support Hero EV Cashout (if you use them it's on you, don't be a dumbass)\n"
    "- Hands involving Splash Pots are fully processed, but the extra profit from Splash drops is calculated and displayed only in the post-conversion report on this page. To get your full profits you need to add them to your winnings in PT4"
)

user_hero_name = st.text_input("Enter your desired PT4 Hero Name:", value="Hero")

uploaded_file = st.file_uploader("Upload CoinPoker hand history .txt file", type="txt", accept_multiple_files=False)

if uploaded_file:
    if not user_hero_name.strip():
        st.error("⚠️ Please enter a Hero Name before converting.")
    else:
        if st.button("🚀 Convert and Generate Report"):
            total_splash_won = 0.0
            splash_hands_count = 0
            total_splashes_on_table = 0
            all_converted_hands = []

            with st.spinner('Analyzing and converting hands...'):
                content = uploaded_file.read().decode('utf-8')
                lines = content.splitlines()

                # Splash Pot Calculator
                raw_hands = content.split("CoinPoker Hand #")
                for raw_hand in raw_hands[1:]:
                    hand_lines = raw_hand.splitlines()
                    splash_in_hand = 0.0
                    for line in hand_lines:
                        if "SPLASH dropped" in line:
                            match = re.search(r"dropped [\$₮]([\d\.]+)", line)
                            if match:
                                splash_in_hand += float(match.group(1))

                    if splash_in_hand > 0:
                        total_splashes_on_table += 1
                        collected_data = {}
                        for line in hand_lines:
                            coll_m = re.match(r"^(.*?)(?: collected )[\$₮]([\d\.]+)( from pot.*)$", line)
                            if coll_m:
                                player = coll_m.group(1).strip()
                                if player == "Hero":
                                    player = user_hero_name
                                amt = float(coll_m.group(2))
                                collected_data[player] = collected_data.get(player, 0.0) + amt

                        if collected_data:
                            # Poprawiona proporcjonalna matematyka zostaje zachowana w interfejsie!
                            total_coll = sum(collected_data.values())
                            if user_hero_name in collected_data and total_coll > 0:
                                hero_share = collected_data[user_hero_name] / total_coll
                                total_splash_won += splash_in_hand * hero_share
                                splash_hands_count += 1

                # Konwersja rąk
                converted_lines = convert_coinpoker_to_pt4_memory(lines, hero_name=user_hero_name)
                all_converted_hands.extend(converted_lines)
                all_converted_hands.append("")

            st.success("✅ Conversion completed successfully!")

            # Wyświetlanie raportu
            st.subheader("📊 Splash Pot Report")
            col1, col2, col3 = st.columns(3)
            col1.metric("Splash Pots on Table", total_splashes_on_table)
            col2.metric(f"Your Splash Pots ({user_hero_name})", splash_hands_count)
            col3.metric("Splash Pot Profit", f"${total_splash_won:.2f}")

            # Przycisk pobierania
            merged_output = "\n".join(all_converted_hands)
            st.download_button(
                label="📥 Download Converted PT4 File",
                data=merged_output,
                file_name=f"PT4_Converted_{uploaded_file.name}",
                mime="text/plain"
            )

# SEKCJA WSPARCIA / TIPÓW
st.divider()
st.markdown(
    "If you found this converter useful and would like to leave a tip, "
    "you can send **ETH (ERC20 network)** to the address below:"
)
st.code("0x93d27d8c9a0398d32ac0015ce0f91060e2aeb348", language="text")
