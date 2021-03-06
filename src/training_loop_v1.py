"""
This file contains the training loop for the agents involved in the
communication/counting task. The loop involves two CountingAgents objects,
a Gym-like environment and includes the optimization procedure
based on Q-Learning.
"""

import datetime

import numpy as np
import torch

from src.MLPAgent import MLPAgent
from src.CNNAgent import CNNAgent
from src.ReplayMemory import ReplayMemory
from src.Reward import Reward
from src.SingleAgentEnv import SingleAgentEnv
from src.QLearning import optimize_model, get_qvalues
from src.utils import test_agent
from torch.utils.tensorboard import SummaryWriter
from torch import nn


def training_loop(env, n_episodes, replay_memory, policy_net,
                  target_net, loss_fn, optimizer, log, visit_history,
                  gamma=0.999, target_update=10,
                  batch_size=128, CL_settings=None):
    """
    Args:
        - env: The Gym-like environment.
        - n_episodes: The number of episodes the agent is going to experience.
        - policy_net: The Policy Network
        - replay_memory: The Replay Memory used to make observations uncorrelated.
        - target_net: The Target Network
        - policy: Policy used to choose the action based on Q-values (either softmax or eps-greedy).
        - loss_fn: The loss function chosen.
        - optimizer: PyTorch implementation of the chosen optimization algorithm
        - log: A TensorBoard SummaryWriter object
        - visit_history: Dict {state: n_visits} used to implement curiosity mechanism
        - gamma: Gamma parameter in the Q-Learning algorithm for long-term reward
        - target_update: Number of episodes to wait before updating the target network
        - batch_size: Size of the batch sampled from the Replay Memory
    """

    if CL_settings is None:
        n_iter = 0
    else:
        n_iter_cl_phase = 0
        n_iter = CL_settings["n_iter"]

    episode_rewards = []

    for episode in range(n_episodes):
        if episode % 1000 == 0:
            print(f"{episode=}")

        # Initialize the environment and state
        state = env.reset()
        done = False

        while not done:
            n_iter += 1
            n_iter_cl_phase += 1
            
            q_values = get_qvalues(state, policy_net)
            action, next_state, reward, done, correct_label = env.step(q_values, n_iter_cl_phase, visit_history)
            episode_rewards.append(reward)

            # for debug
            if episode % 1000 == 0:
                print(env.obs)
                print(f"Action chosen: {env.actions_dict[action]}")

            last_q_values = q_values[0, -env.max_CL_objects:]
            for label, q_value in enumerate(last_q_values):
                log.add_scalar(f'q_values/label_{label+1}_obs_{env.obs_label}',
                               q_value, n_iter)

            reward = torch.tensor([reward])  # , device=device) TODO: CUDA

            if done:
                next_state = None
                
            # Store the transition in memory
            replay_memory.push(state, q_values, next_state, reward)
            
            # Move to the next state
            state = next_state

            # Perform one step of the optimization (on the policy network)
            loss_val = optimize_model(replay_memory, batch_size, policy_net, target_net, loss_fn, optimizer, gamma)
            
            if loss_val is not None:
                log.add_scalar(f'Loss/train', loss_val.item(), n_iter)

        # Update the target network every target_update episodes
        if episode % target_update == 0:
            # Copy the weights of the policy network to the target network
            target_net.load_state_dict(policy_net.state_dict())

            avg_episode_reward = np.mean(episode_rewards)
            log.add_scalar(f'Mean{target_update}EpisodeReward',
                           avg_episode_reward,
                           episode / target_update)
            episode_rewards = []

    CL_settings["n_iter"] = n_iter
    print("Done")


if __name__=='__main__':

    # ENVIRONMENT
    obs_dim = 5                     # assume squared observation
    min_CL_objects = 3
    max_CL_objects = 3              # the maximum number of objects counted in the whole CL experience
    max_object_size = 2
    n_objects_sequence = range(min_CL_objects, max_CL_objects + 1)
    n_episodes_per_phase = 40000
    max_episode_length = 1          # timesteps
    generate_random_nobj = True
    random_object_size = True
    random_finger_position = False

    # TASK
    n_fingers = 2
    n_actions = 4 * n_fingers + 1   # fingers move in 4 dimensions, one can write

    # OPTIMIZATION
    gamma = 0.995                   # gamma parameter for the long term reward
    replay_memory_capacity = 10000  # Replay memory capacity
    lr = 1.5e-3                       # Optimizer learning rate
    batch_size = 128                # Number of samples to take from the replay memory for each update
    target_net_update = 50          # Frequency of update of the target net

    # AGENT
    MLP = False
    CNN = True

    if MLP:
        agent_params = {
            'input_dim': obs_dim,
            'n_layers': 4,
            'vis_rep_size': 32,
            'action_space_size': n_actions + max_CL_objects,
        }
        policy_agent = MLPAgent(**agent_params)
        target_agent = MLPAgent(**agent_params)

    elif CNN:
        CNN_agent_params = {
            'input_dim': obs_dim,
            'input_channels': 4,
            'n_kernels': 4,
            'vis_rep_size': None,
            'action_space_size': n_actions + max_CL_objects,
        }
        policy_agent = CNNAgent(**CNN_agent_params)
        target_agent = CNNAgent(**CNN_agent_params)

    memory = ReplayMemory(replay_memory_capacity)

    optimizer = torch.optim.SGD(policy_agent.parameters(), lr=lr, momentum=0.9)
    # optimizer = torch.optim.Adam(policy_agent.parameters())
    loss_fn = nn.SmoothL1Loss()

    # REWARD
    reward_params = {
        "bad_label_punishment": True,
        "curiosity": False,
        "time_penalty": .1,
    }
    reward = Reward(**reward_params)

    # CL
    current_time = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    writer = SummaryWriter(log_dir=f'./log/{current_time}')
    print(f"Logging in './log/{current_time}'")

    CL_settings = {
        "n_iter": 0,
    }

    state_visit_history = {}

    for n_objects in n_objects_sequence:
        n_iter = CL_settings["n_iter"]
        print(f"## CL ## max n. objects = {n_objects}, n_iter = {n_iter}")

        env_params = {
            'max_CL_objects': max_CL_objects,
            'CL_phases': len(n_objects_sequence),
            'max_episode_objects': n_objects,
            'obs_dim': obs_dim,
            'max_episode_length': max_episode_length,
            'n_actions': n_actions + max_CL_objects,
            'n_episodes_per_phase': n_episodes_per_phase,
            'max_object_size': max_object_size,
            'generate_random_nobj': generate_random_nobj,
            'random_object_size': random_object_size,
            'random_finger_position': random_finger_position,
        }

        # re-create the environment
        env = SingleAgentEnv(reward, **env_params)

        training_loop(env, n_episodes_per_phase, memory, policy_agent, target_agent, loss_fn, optimizer, writer,
                      state_visit_history,
                      gamma=gamma,
                      batch_size=batch_size,
                      CL_settings=CL_settings,
                      target_update=target_net_update,
        )

    test_agent(policy_agent, env, 500, CL_settings['n_iter'])