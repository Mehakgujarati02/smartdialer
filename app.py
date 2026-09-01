import streamlit as st

from smartdialer.agent_manager import AgentManager
from smartdialer.borrower_manager import BorrowerManager
from smartdialer.call_manager import CallManager
from smartdialer.call_allocator import CallAllocator
from smartdialer.safety_controller import SafetyController
from smartdialer.pacing_engine import PacingEngine
from smartdialer.event_processor import EventProcessor
from smartdialer.progressive_dialer import ProgressiveDialer
from smartdialer.provider_a import ProviderA
from smartdialer.provider_b import ProviderB
from smartdialer.models import Agent, AgentStatus, Borrower, CallStatus


st.set_page_config(
    page_title="SmartDialer",
    page_icon="📞",
    layout="wide"
)


st.title("📞 SmartDialer")
st.caption("Predictive Progressive Dialing System")


MAX_CONCURRENCY = 10


# -------------------------
# Sidebar configuration
# -------------------------

st.sidebar.header("Campaign Configuration")

number_of_agents = st.sidebar.slider(
    "Number of Agents",
    min_value=1,
    max_value=20,
    value=5
)

number_of_borrowers = st.sidebar.slider(
    "Number of Borrowers",
    min_value=1,
    max_value=100,
    value=20
)

provider_name = st.sidebar.selectbox(
    "Telecom Provider",
    ["Provider A", "Provider B"]
)


# -------------------------
# Current pacing (preview before the run)
# -------------------------

preview_agent_manager = AgentManager()

for i in range(number_of_agents):
    preview_agent_manager.add_agent(
        Agent(id=f"A{i}", name=f"Agent {i}", status=AgentStatus.AVAILABLE)
    )

pacing_engine_preview = PacingEngine(
    preview_agent_manager,
    campaign_max_concurrency=MAX_CONCURRENCY
)

recommended_pacing = pacing_engine_preview.calculate_capacity(
    active_calls=0
)


st.subheader("Campaign Overview")

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric(
        "Agents",
        number_of_agents
    )

with col2:
    st.metric(
        "Borrowers",
        number_of_borrowers
    )

with col3:
    st.metric(
        "Max Concurrency",
        MAX_CONCURRENCY
    )

with col4:
    st.metric(
        "Recommended Pacing",
        recommended_pacing
    )


# -------------------------
# Run simulation
# -------------------------

st.divider()

if st.button("▶️ Run Simulation", use_container_width=True):

    # Build the population for this run
    agent_manager = AgentManager()

    for i in range(number_of_agents):
        agent_manager.add_agent(
            Agent(id=f"A{i}", name=f"Agent {i}", status=AgentStatus.AVAILABLE)
        )

    borrower_manager = BorrowerManager()

    for i in range(number_of_borrowers):
        borrower_manager.add_borrower(
            Borrower(
                id=f"B{i}",
                name=f"Borrower {i}",
                phone_number=f"90000{i:05d}",
                priority=0
            )
        )

    call_manager = CallManager()

    allocator = CallAllocator(
        agent_manager,
        borrower_manager
    )

    safety_controller = SafetyController(
        max_global_concurrency=MAX_CONCURRENCY,
        max_campaign_concurrency=MAX_CONCURRENCY
    )

    pacing_engine = PacingEngine(
        agent_manager,
        campaign_max_concurrency=MAX_CONCURRENCY
    )

    event_processor = EventProcessor(call_manager)

    # Realistic per-provider characteristics, per the assignment's own
    # description ("Provider A: low failure rate", "Provider B:
    # occasional timeouts"). No seed -> genuinely random each run, so
    # re-running the simulation gives different (realistic) outcomes
    # instead of the same deterministic 100% every time.
    if provider_name == "Provider A":
        provider = ProviderA(failure_rate=0.05)
    else:
        provider = ProviderB(timeout_rate=0.15)

    dialer = ProgressiveDialer(
        pacing_engine,
        safety_controller,
        allocator,
        call_manager,
        event_processor,
        provider
    )

    # -------------------------
    # Drive the dialer batch by batch until no more calls can launch
    # -------------------------

    calls_attempted = 0
    calls_connected = 0
    calls_completed = 0
    calls_failed = 0

    # Safety cap on rounds so a stuck loop can never hang the app.
    max_rounds = number_of_borrowers + 5

    for _ in range(max_rounds):

        batch = dialer.launch_calls()

        if not batch:
            break

        for call in batch:

            calls_attempted += 1

            dialer.process_call(call)

            if call.status in (CallStatus.CONNECTED, CallStatus.COMPLETED):
                calls_connected += 1

            if call.status == CallStatus.COMPLETED:
                calls_completed += 1
                dialer.complete_call(call.id)

            elif call.status == CallStatus.FAILED:
                calls_failed += 1
                dialer.fail_call(call.id)

            else:
                # Provider left the call in a non-terminal state.
                # Mark it failed so the agent/borrower/capacity are
                # released instead of leaking.
                calls_failed += 1
                call_manager.transition(call.id, CallStatus.FAILED)
                dialer.fail_call(call.id)

    metrics = {
        "calls_attempted": calls_attempted,
        "calls_connected": calls_connected,
        "calls_completed": calls_completed,
        "calls_failed": calls_failed
    }

    st.subheader("Simulation Results")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            "Calls Attempted",
            metrics["calls_attempted"]
        )

    with col2:
        st.metric(
            "Calls Connected",
            metrics["calls_connected"]
        )

    with col3:
        st.metric(
            "Calls Completed",
            metrics["calls_completed"]
        )

    with col4:
        st.metric(
            "Calls Failed",
            metrics["calls_failed"]
        )

    # Calculate answer rate
    attempted = metrics["calls_attempted"]

    if attempted > 0:
        answer_rate = (
                metrics["calls_connected"] / attempted
        )
    else:
        answer_rate = 0

    st.subheader("Performance")

    col1, col2 = st.columns(2)

    with col1:
        st.metric(
            "Answer Rate",
            f"{answer_rate:.1%}"
        )

    with col2:
        st.metric(
            "Safety Capacity After Run",
            safety_controller.active_campaign_calls
        )

    st.success("Simulation completed successfully.")

else:

    st.info(
        "Configure the campaign from the sidebar and click "
        "'Run Simulation' to start."
    )
