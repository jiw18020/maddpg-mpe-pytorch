from copy import deepcopy
from typing import List

import numpy as np
import torch
from torch import nn, Tensor
from torch.nn.functional import gumbel_softmax, one_hot
from torch.optim import Adam
import torch.nn.functional as F


class Agent:
    """single agent in MADDPG"""

    def __init__(self, obs_dim, act_dim, global_obs_dim, actor_lr, critic_lr, device):
        # the actor output logit of each action
        self.actor = MLPNetwork(obs_dim, act_dim).to(device)
        # critic input all the states and actions
        # if there are 3 agents for example, the input for critic is (obs1, obs2, obs3, act1, act2, act3)
        self.critic = MLPNetwork(global_obs_dim, 1).to(device)
        self.actor_optimizer = Adam(self.actor.parameters(), lr=actor_lr)
        self.critic_optimizer = Adam(self.critic.parameters(), lr=critic_lr)
        self.target_actor = deepcopy(self.actor).to(device)
        self.target_critic = deepcopy(self.critic).to(device)
        self.device = device

    @staticmethod
    def gumbel_softmax(logits, tau=1, eps=1e-20):
        epsilon = torch.rand_like(logits)
        logits += -torch.log(-torch.log(epsilon + eps) + eps)
        return F.softmax(logits / tau, dim=-1)

    def action(self, obs, *, model_out=False):
        # this method is called in the following two cases:
        # a) interact with the environment, where input is a numpy.ndarray
        # NOTE that the output is a tensor, you have to convert it to ndarray before input to the environment
        # b) when update actor, calculate action using actor and states,
        # which is sampled from replay buffer with size: torch.Size([batch_size, state_dim])

        logits = self.actor(obs)  # torch.Size([batch_size, action_size])
        # action = gumbel_softmax(action, tau=1, hard=False)
        action = self.gumbel_softmax(logits)
        if model_out:
            return action, logits
        return action  # torch.Size([batch_size, action_size])

    def target_action(self, obs):
        # when calculate target critic value in MADDPG,
        # we use target actor to get next action given next states,
        # which is sampled from replay buffer with size torch.Size([batch_size, state_dim])

        logits = self.target_actor(obs)  # torch.Size([batch_size, action_size])
        # action = gumbel_softmax(logits, hard=False)
        action = self.gumbel_softmax(logits)
        return action.squeeze(0).detach()  # onehot tensor with size: torch.Size([batch_size, action_size])

    def critic_value(self, state_list: List[Tensor], act_list: List[Tensor]):
        x = torch.cat(state_list + act_list, 1)
        return self.critic(x).squeeze(1)  # tensor with a given length

    def target_critic_value(self, state_list: List[Tensor], act_list: List[Tensor]):
        x = torch.cat(state_list + act_list, 1)
        return self.target_critic(x).squeeze(1)  # tensor with a given length

    def update_actor(self, loss):
        self.actor_optimizer.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(self.actor.parameters(), 0.5)
        self.actor_optimizer.step()

    def update_critic(self, loss):
        self.critic_optimizer.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(self.critic.parameters(), 0.5)
        self.critic_optimizer.step()


class MLPNetwork(nn.Module):
    def __init__(self, in_dim, out_dim, hidden_dim=64, non_linear=nn.ReLU(), last_layer=None):
        super(MLPNetwork, self).__init__()

        modules = [
            nn.Linear(in_dim, hidden_dim),
            non_linear,
            nn.Linear(hidden_dim, hidden_dim),
            non_linear,
            nn.Linear(hidden_dim, out_dim),
        ]
        if last_layer is not None:
            modules.append(last_layer)
        self.net = nn.Sequential(*modules).apply(self.init)

    @staticmethod
    def init(m):
        """init parameter of the module"""
        gain = nn.init.calculate_gain('relu')
        if isinstance(m, nn.Linear):
            torch.nn.init.xavier_uniform_(m.weight, gain=gain)
            m.bias.data.fill_(0.01)

    def forward(self, x):
        return self.net(x)
